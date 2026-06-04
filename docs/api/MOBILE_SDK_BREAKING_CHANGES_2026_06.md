# Mobile SDK breaking changes — 2026-06 (Sprint 3 + bug-fix sprint)

> Audience: mobile (iOS, Android) and any first-party HTTP client of the NOVA
> backend. **Action required** for clients shipped before 2026-06-03.

## TL;DR

1. **`Idempotency-Key` is now hard-required** on all mutating, side-effectful
   POST endpoints below. Sending the request without the header returns
   `422 Unprocessable Entity` (formerly `400` or silent accept).
2. **Key contract**: header value MUST be a RFC 4122 UUIDv4. Malformed →
   `422` `idempotency_key_invalid_uuid4`.
3. **Body-mismatch on replay** (same key, different body) → `409 Conflict`
   `idempotency_key_body_mismatch`. Clients MUST treat this as a programming
   error (do not retry).
4. **Replay of a completed request** with the same key returns the cached
   response (`200/201/202` as originally returned). Side effects do NOT
   re-execute. TTL: 24 h.
5. **Two endpoints explicitly DO NOT accept `Idempotency-Key`**: `/coach/chat`
   (SSE stream) and `/tracking/fasting/start` (single-active guard). Sending
   the header is ignored, not rejected.
6. **`429 Too Many Requests` and `503 Service Unavailable`** now ship
   `Retry-After` per RFC 6585. Clients MUST honour it.

---

## 1. Endpoints requiring `Idempotency-Key`

All entries: header alias is `Idempotency-Key`, value is UUIDv4 string,
TTL 24 h, replay returns cached body byte-for-byte with the original status
code.

| Method | Path | Notes |
|--------|------|-------|
| `POST` | `/plan/generate` | Enqueues `generate_plan_task`. Returns `202 Accepted` with `task_id`. Replay returns same `task_id`. |
| `POST` | `/logs/food/text` | Text food log. Returns `201 Created` with `log_id`. |
| `POST` | `/logs/food/manual` | Structured manual food entry. Returns `201`. |
| `POST` | `/logs/food/photo` | Multipart upload (≤8 MB). Returns `202 Accepted` with `job_id`. |
| `POST` | (vision job confirm / amend — see router) | Same contract as above. |

**Source of truth**: `grep -rn require_idempotency_key app/` plus the
manual header guards in `app/vision/presentation/router.py`.

### Failure modes (HTTP)

| Status | Error code (envelope) | When |
|--------|------------------------|------|
| `422` | `idempotency_key_required` | Header absent on a required endpoint. |
| `422` | `idempotency_key_invalid_uuid4` | Header present but not UUIDv4. |
| `409` | `idempotency_key_body_mismatch` | Same key, different request body (SHA256 of canonical body diverges from the record). |
| `200/201/202` | (cached response replayed) | Same key + same body within TTL → server returns the stored response. No side effects. |

**Important**: a `409` is NEVER retryable with the same key. The mobile
client MUST either (a) reuse the original body or (b) generate a fresh
UUIDv4 for a logically-new request.

---

## 2. Endpoints that intentionally do NOT support `Idempotency-Key`

| Path | Why |
|------|-----|
| `POST /coach/chat` | Streaming SSE endpoint. Idempotency semantics don't compose with token-by-token streaming (the same request will not produce a byte-identical stream because the LLM samples). Retries cost a full LLM call — clients MUST debounce locally instead. |
| `POST /tracking/fasting/start` | Single-active-fast guard. The server already enforces "at most one active fast per user" via DB unique partial index; idempotency would be redundant and ambiguous when the previous fast is in a different state. Concurrent starts are handled by the guard and return `409 fast_already_active`. |

Mobile clients SHOULD NOT send `Idempotency-Key` on these. The header is
ignored (no error), but tooling generating UUIDs unnecessarily wastes
storage and engineer attention.

---

## 3. Mobile-client guidance

### 3.1 Key generation

- Generate a fresh UUIDv4 per **user-initiated action**, NOT per HTTP
  attempt. The same key must be reused on retries of the same logical
  action.
- Use the platform-native UUID generator (`UUID().uuidString` on iOS,
  `UUID.randomUUID().toString()` on Android). Both default to RFC 4122 v4.
- Lowercase or mixed-case both accepted; canonical form recommended is
  lowercase.

### 3.2 Caching the key

- Persist the key alongside the in-flight request in your retry queue
  (Core Data, Room, SQLite, whatever the client uses).
- Cache lifetime: **at least 24 h** (matches server TTL). After 24 h the
  server may have purged the key; replay would re-execute the side effect.
- Key MUST be discarded once the original request returns a terminal
  status (`201`, `202`, `4xx ≠ 408/429/503`, or `200` cached replay).

### 3.3 Retry behaviour

| Server status | Action |
|----------------|--------|
| `2xx` | Done. Discard key. |
| `408`, `5xx` (no `Retry-After`) | Retry with exponential backoff, **same key**. Cap retries at 5. |
| `429`, `503` (with `Retry-After`) | Sleep at least `Retry-After` seconds, then retry with **same key**. |
| `409 idempotency_key_body_mismatch` | Programming bug. Do NOT retry. Emit local error, surface to client log. |
| `422 idempotency_key_required` | Programming bug. SDK forgot the header. Fix in SDK, not at runtime. |
| Other `4xx` | Do NOT retry. Surface to user. |

### 3.4 `Retry-After` header (RFC 6585)

- Format: either integer seconds (e.g. `Retry-After: 30`) or HTTP-date.
  Mobile clients MUST handle the integer form; HTTP-date is optional.
- On `429`: this is a rate-limit signal. Respect it, then retry.
- On `503`: maintenance / degraded mode. Respect it; if absent, treat as
  60 s default.

---

## 4. Migration steps for client SDKs

1. **Regenerate the OpenAPI client** against the new spec:

   ```bash
   # iOS / Swift
   swift run swift-openapi-generator generate --output Sources/NovaSDK \
       --mode types,client --input openapi.json
   ```

   (Or the equivalent for `openapi-generator-cli`, `kotlinx-openapi-bindgen`,
   etc.)
2. **Update the request builder layer** to always include `Idempotency-Key`
   on the endpoints listed in §1. Recommended pattern: middleware /
   interceptor that injects the header from the retry-queue record.
3. **Add lint rules**:
   - Forbid building a request to any §1 endpoint without setting the key.
   - Forbid mutating the request body of an in-flight retry without
     rotating the key (otherwise `409` on the next attempt).
4. **Test plan** (minimum):
   - Unit test: builder rejects missing key for `/plan/generate`,
     `/logs/food/*`.
   - Integration test (staging): retry the same `POST /plan/generate` twice
     with the same key — second call returns the same `task_id` and does
     NOT enqueue a second worker job.
   - Integration test: mutate the body on retry → expect `409`.
   - Integration test: malformed UUID (e.g. `"abc"`) → expect `422`.
   - Integration test: `429` response carries `Retry-After`; sleep and
     retry succeeds.
5. **Telemetry**: emit a client-side counter for every `409` and `422`
   on idempotency. Either indicates a SDK bug.

---

## 5. Compatibility window

- Server enforces the new contract from **2026-06-03 PROD deploy**.
- No grace period: missing-header requests on §1 endpoints will return
  `422` immediately.
- Clients shipped before 2026-06-03 MUST be force-updated or feature-gated
  off these endpoints.

---

## 6. References

- Internal: `app/core/idempotency.py` (canonical implementation).
- Internal: `app/identity/presentation/dependencies.py::idempotency_key`
  (the Depends() resolver).
- RFC draft: `draft-ietf-httpapi-idempotency-key-06`.
- RFC 6585 §4 `Retry-After` semantics for `429`.
- RFC 7231 §7.1.3 `Retry-After` for `503`.
- RFC 4122 §4.4 UUIDv4 format.
