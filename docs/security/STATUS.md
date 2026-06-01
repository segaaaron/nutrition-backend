# Security Status — NOVA Backend

**Last updated:** 2026-06-01
**Owner:** Miguel Ángel Saravia
**Sprints shipped:** S0 (10 items) + S1-quick (4 items) + ErrorTracker refactor
**Policy:** OSS-only, zero paid plugins, growth-driven activation
**Source of truth for triggers:** `docs/security/BACKLOG.md`

---

## 🎯 Defense matrix — what protects NOVA TODAY

| Attack vector | Defense | Implementation |
|---------------|---------|----------------|
| **BOLA** — user A reads user B data via ID | `assert_owns()` helper across all `/v1/*/{id}` endpoints | `app/identity/presentation/dependencies.py` |
| **BOPLA** — mass assignment via PATCH | Pydantic `extra='forbid'` on all input schemas | 10 schemas hardened, regression test enforces |
| **Broken auth** — token theft / replay | PyJWT RS256 + Redis denylist on logout + kid rotation | `app/identity/infrastructure/jwt_signer.py` |
| **Resource abuse** — DoS or cost drain | Cost cap $1.50/user/day + Redis sliding window + per-IP cap | `app/core/cost_cap.py` + `app/core/ip_rate_limit.py` |
| **SSRF** — internal network probing | `safe_async_client()` blocks RFC1918/metadata/loopback | `app/core/ssrf_guard.py` |
| **MITM / sniffing** — Proxyman / Charles / Burp | User-Agent + Via header detection, prod=reject | `app/core/anti_sniff.py` |
| **Misconfiguration** | HSTS/CSP/Frame/Referrer/Permissions + CORS lock | `app/core/security_headers.py` |
| **Improper inventory exposure** | `/docs`, `/redoc`, `/openapi.json` disabled in prod | `app/main.py` |
| **Webhook spoof billing** | HMAC-SHA256 strict on MercadoPago + Stripe SDK native | `app/billing/gateways.py` |
| **Idempotency loss** | Dual-write Redis + DB fallback table | `app/identity/presentation/dependencies.py` + migration 0007 |
| **Prompt injection LLM** | Hard refuse pre-LLM, security event log | `app/coach/infrastructure/intent_classifier.py` |
| **Off-topic LLM tokens** | Refuse template path, zero cost | Same |
| **Polyglot uploads** (PHP/SVG/EXE as .jpg) | Magic-byte sniff verifies declared MIME | `app/imaging/domain/mime_sniff.py` |
| **Data poisoning tracking** | Physiological bounds + delta guard | `app/tracking/domain/anomaly.py` |
| **Function-level auth** | `require_role(Role.X)` dependency | `app/identity/domain/roles.py` |
| **Secret leak in commits** | gitleaks CI on every PR + push | `.gitleaks.toml` + `.github/workflows/security.yml` |
| **Vulnerable deps** | pip-audit + dependabot weekly bumps | `.github/dependabot.yml` |
| **Container CVEs** | trivy fs + config scan | `.github/workflows/security.yml` |
| **Code-level vulns** | bandit + semgrep SAST | Same |
| **pgvector tenancy leak** | Regression test fails if new vector model unclassified | `tests/unit/test_pgvector_tenancy_audit.py` |
| **Production error visibility** | Local ErrorTracker — ring + JSONL + admin endpoint + Prom counter | `app/core/error_tracker.py` |
| **Audit trail** | structlog JSON to stdout + JSONL file | `app/core/logging.py` + ErrorTracker file layer |
| **Mobile app crashes** | Firebase Crashlytics (mobile team scope) | iOS/Android repos |

**Coverage:** OWASP API Top 10 (2023) — 8/10 fully addressed, 2/10 partial (premium gating + Turnstile deferred).
**Coverage:** ASVS L2 — V1-V14 audited, gaps documented in PLAN.md.

---

## 📦 What's in code right now

### Middleware stack (order matters)

```
Request
  ↓
SecurityHeadersMiddleware    ← HSTS/CSP/Frame/etc on every response
AntiSniffMiddleware           ← Reject Proxyman/Charles in prod
IpRateLimitMiddleware         ← Volumetric cap per IP
ErrorTrackerMiddleware        ← Catch uncaught → ring + JSONL + Prom
GZipMiddleware                ← Compression
RequestIdMiddleware           ← x-request-id propagation
HttpMetricsMiddleware         ← Prometheus per-endpoint
CORSMiddleware                ← Origin allowlist
  ↓
FastAPI routers
```

### Per-bounded-context invariants

| Context | Security invariants enforced |
|---------|-----------------------------|
| **identity** | Argon2id pw hash, PyJWT RS256, kid rotation, denylist Redis, OAuth verifiers SSRF-safe |
| **billing** | Stripe + MP HMAC strict, idempotency dual-write, webhook event dedupe UNIQUE |
| **vision** | MIME sniff magic bytes, EXIF strip GPS, cost cap pre-check, 8MB max upload |
| **coach** | 3-layer guardrails (medical + offtopic + prompt injection), cost cap, refuse pre-LLM |
| **tracking** | Anomaly guard physiological bounds + delta, BOLA filter per repo |
| **plan** | BOLA assert_owns, BOPLA Pydantic strict, recipe global catalog tenancy |
| **profile** | BOPLA forbid (no role escalation via PATCH), allergens trigger hard-exclusion |
| **recipes** | Global catalog tenancy (documented), hybrid search tenant-filtered |

---

## 💰 Cost summary (zero paid SaaS, zero infrastructure beyond existing)

| Service | Status | Monthly |
|---------|--------|---------|
| OpenAI | Pay-per-token (only on real usage) | $0 today, ~$0.022/user/day estimated |
| Stripe | Commission on revenue (only if you charge) | 2.9% + $0.30 per tx |
| MercadoPago | Commission on revenue | 3.5-5% per tx |
| Hostinger KVM 2 | Existing plan | included |
| Cloudflare | Free tier | $0 |
| GitHub Actions | Free tier | $0 (2k min/mo private) |
| ~~Sentry~~ | Removed, replaced by local ErrorTracker | $0 |
| Firebase Crashlytics | Mobile-only, free tier | $0 |
| **Net new cost from security work** | — | **$0/mo** |

---

## ✅ Sprint S0 — pre-launch hardening (shipped 2026-06-01)

| ID | Item | OWASP/ISO | Commit |
|----|------|-----------|--------|
| S0-A | Security headers + CORS lock + /docs prod gate | API8, API9, ASVS V9/V14 | `d9d6b4e` |
| S0-B | BOLA audit + `assert_owns()` helper | API1, ASVS V4 | `91d54e9` |
| S0-C | Pydantic `extra='forbid'` (10 schemas) | API3, ASVS V5 | `805d63d` |
| S0-D | JWT revocation Redis denylist | API2, ASVS V3 | `448d16a` |
| S0-E | SECURITY.md + VDP | ISO 29147/30111 | `bcf6dde` |
| S0-F | AntiSniffMiddleware (Proxyman/Charles/Burp) | API8, ASVS V9 | `44d2dad` |
| S0-H | pgvector tenancy audit + regression guard | API1 | `64e6741` |
| S0-I | SSRF guard `safe_async_client` | API7 | `b631203` |
| S0-J | JWT key rotation (`kid` header) | ASVS V2 | `5ce650a` |
| S0-K | Per-IP global rate-limit middleware | API4 | `3c168ac` |

**Pre-S0 hardening (same branch):**
- PyJWT migration (jose CVE surface eliminated) — `074dd74`
- ~~Sentry activated~~ removed, replaced by ErrorTracker — `8a82d63`
- MercadoPago HMAC-SHA256 strict — `f7fe5f6`
- Idempotency DB fallback — `e28476e`
- Coach guardrails expanded (GLP-1 drugs + offtopic + injection) — `ac6c9e0`
- OpenTelemetry stack removed — `759d3ba`

---

## ✅ Sprint S1-quick (shipped 2026-06-01)

| ID | Item | OWASP/ISO | Commit |
|----|------|-----------|--------|
| S1-1 | CI security scans batch (bandit + semgrep + gitleaks + pip-audit + trivy + dependabot) | A.14.2 + A.9.2 + A.12.6 | `e619434` |
| S1-2 | RBAC matrix (Role enum + `require_role()`) | API5, ASVS V4 | `2143573` |
| S1-3 | MIME sniff verification vision uploads | ASVS V12 | `3aa58de` |
| S1-4 | Anomaly guard tracking weight | API4 | `398a04d` |

---

## ⏸️ Pending — Sprint S1 remaining (deferred with triggers)

| Item | Effort | Trigger |
|------|--------|---------|
| Data classification matrix | 2h | Pre-launch legal review OR first DSAR |
| Data retention cron (food_logs/vision_jobs purge) | 4h | DB >5GB OR 90d post-launch |
| HSTS preload submit (manual hstspreload.org) | 30min | Domain stable 30d — **owner manually submits** |
| Privacy Policy + ToS templates | 4h | Pre-launch lawyer review |
| Cookie consent banner spec | 2h | EU launch confirmed |

## ⏸️ Pending — Sprint S2 deferred

| Item | Effort | Trigger |
|------|--------|---------|
| pgcrypto field-level encryption (conditions, allergens) | 8h | First B2B customer OR regulator inquiry |
| MFA TOTP (delete account + payment method) | 6h | First fraud incident OR 1k paying users |
| OWASP ZAP baseline in CI | 4h | API surface stable (>30 endpoints maturing) |
| SOPS + age secrets | 6h | Team ≥2 members |
| Loki + Promtail self-hosted SIEM | 4h | Dokploy logs insufficient OR self-host preferred |
| ROPA — Record of Processing | 6h | GDPR DSAR received OR EU large-scale processing |
| DPIA-lite | 4h | Same trigger as ROPA |
| App attestation (Apple App Attest / Play Integrity) | 6h | Mobile app published to stores |

## ⏸️ Pending — Sprint S3 deferred

| Item | Effort | Trigger |
|------|--------|---------|
| WAL archiving PITR | 4h | 1k DAU OR first data-loss incident |
| Disaster Recovery drill | 4h | Production data + Q+1 |
| Access review log + cron | 3h | Team ≥3 members |
| Threat model formal STRIDE | 8h | Pre-Series A OR enterprise audit |
| Incident Response runbook | 4h | First incident OR pre-launch hard date |
| Vulnerability tracking CVD program enhancement | 3h | First VDP report received |
| Compliance audit prep | 4h | ISO certification ambition declared |

---

## 🚫 Declined / out of scope

| Item | Reason |
|------|--------|
| **Pen-test externo** (~$1.5k) | Paid SaaS — declined per owner policy. Re-evaluate at $5k MRR + funding. |
| **Backup off-site B2/Hetzner** ($1-5/mo) | Paid — declined. Hostinger weekly snapshot covers MVP. Re-evaluate at 100+ paying users. |
| **Sentry SaaS** | Paid (5k free tier risk of paywall at scale). Replaced by local ErrorTracker. Mobile crashes go to Firebase Crashlytics. |
| **Cloudflare Turnstile signup** | Deferred until CF domain configured. |

---

## 📊 Numbers

| Metric | Value |
|--------|-------|
| Sprints shipped | S0 + S1-quick |
| Total commits security work | ~30 |
| New code added | ~2,400 LoC |
| New tests added | ~190 (all green) |
| Pre-existing test regressions | 0 |
| Net new monthly cost | $0 |
| Net new RAM footprint | <5 MB |
| Paid SaaS dependencies | 0 |
| Lines removed (dead deps) | ~370 (OpenTelemetry + Sentry + snack script) |

---

## 🔄 Replacements summary

| Removed | Replaced with | Cost change | Trade-off |
|---------|---------------|-------------|-----------|
| `python-jose` | `pyjwt[crypto]` | $0 | CVE surface eliminated |
| OpenTelemetry stack (5 pkgs) | Prometheus existing | -15MB pip | Tracing deferred until needed |
| Sentry SDK + SaaS | ErrorTracker local | $0 | No external dashboard, JSON via curl |
| `python-magic` system dep | Hardcoded magic bytes | $0 | No libmagic install required |

---

## 📋 Pre-deploy checklist (owner manual actions)

When deploying to production for the first time:

1. **Secrets in Dokploy env:**
   - [ ] `MERCADOPAGO_WEBHOOK_SECRET` (from MP dashboard)
   - [ ] `STRIPE_API_KEY` + `STRIPE_WEBHOOK_SECRET`
   - [ ] `OPENAI_API_KEY`
   - [ ] `JWT_PRIVATE_KEY_PATH` + `JWT_PUBLIC_KEY_PATH` (mount RSA keys)
   - [ ] Optional: `JWT_SIGNING_KEYS` for multi-kid rotation from day 1
   - [ ] `ENV=prod`

2. **Database:**
   - [ ] `alembic upgrade head` (applies migration 0007 idempotency_keys)
   - [ ] Verify TimescaleDB + pgvector extensions enabled

3. **Filesystem:**
   - [ ] Mount persistent volume for `/var/log/nova/` (ErrorTracker JSONL)
   - [ ] Optional logrotate config: rotate daily, keep 30 days, compress

4. **Smoke tests:**
   - [ ] `GET /healthz` → 200
   - [ ] `GET /docs` → 404 (prod gate confirmed)
   - [ ] `GET /openapi.json` → 404 (prod gate confirmed)
   - [ ] Webhook MP signed → 200; unsigned → 400
   - [ ] Signup + login flow E2E
   - [ ] `GET /admin/errors/recent` with admin JWT → 200

5. **Monitoring setup:**
   - [ ] Grafana scrape `/metrics` (Prometheus)
   - [ ] Alert rule `nova_unhandled_errors_total[5m] > 5` → notify
   - [ ] Alert rule `circuit_breaker_state == 2` for >2min → page
   - [ ] Hostinger weekly backup confirmed enabled

---

## 🔔 When to revisit this document

- After any new bounded context added
- After any security-related commit
- Quarterly review cycle
- Before major release
- After any incident

Last review: 2026-06-01 (post Sprint S0 + S1-quick + ErrorTracker refactor).
