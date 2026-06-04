"""Idempotency-Key middleware/helpers (RFC draft-ietf-httpapi-idempotency-key-06).

Enforced explicitly per-endpoint via ``require_idempotency_key`` (no global
middleware whitelist — see note on IDEMPOTENCY_TTL below). Current endpoints
that hard-require the header:
    POST /v1/plan/generate
    POST /v1/plan/me/swap/{...}
    POST /v1/plan/me/recalibrate
    POST /v1/profile/me/onboarding

Contract:
    - Client MUST send ``Idempotency-Key: <uuid4>``. Malformed -> 400.
    - First request: handler runs; response body + status are persisted
      24h keyed by (user_id, path, key).
    - Replay within 24h: cached body + status returned without re-running
      the handler. Mismatched request body with same key -> 409 (raised
      by the caller after comparing fingerprints; this module persists
      a fingerprint alongside the body to make that check possible).
    - Concurrent requests with the same key serialise via
      ``pg_advisory_xact_lock(hashtext(key))`` — the second request
      blocks until the first commits, then sees the cached row.

Storage: ``idempotency_keys`` table (migration 0007). Redis is *not*
required by this module; the existing Redis-layered impl in
``app/identity/presentation/dependencies.py`` remains the fast path for
endpoints already wired to it.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.errors import ValidationError

# RFC 4122 §3 — UUIDv4 canonical form. Strict: lowercase hex only.
_UUID4_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")

IDEMPOTENCY_TTL = timedelta(hours=24)

# Note: idempotency enforcement is endpoint-explicit (each handler calls
# ``require_idempotency_key`` directly). A module-level whitelist was
# considered but removed (2026-06-03 hygiene sprint) because it never had
# a middleware enforcing it — keeping it would invite bit-rot drift between
# the constant and the real enforcement surface. Add a router-level
# dependency on the affected endpoints instead.


def validate_idempotency_key(value: str) -> str:
    """Validate UUIDv4 format. Raises ValidationError(400) on mismatch."""
    if not isinstance(value, str) or not _UUID4_RE.match(value):
        raise ValidationError(
            "idempotency_key_invalid_uuid4",
            field="Idempotency-Key",
        )
    return value


def fingerprint_body(body: bytes) -> str:
    """SHA-256 of raw request body — used to detect body mismatch on replay."""
    return hashlib.sha256(body).hexdigest()


def storage_key(user_id: str | None, path: str, raw_key: str) -> str:
    """Composite storage key. Mirrors identity layer's redis key shape."""
    composite = f"{user_id}:{path}:{raw_key}"
    return "idem:" + hashlib.sha256(composite.encode()).hexdigest()


@dataclass(frozen=True)
class CachedResponse:
    """Persisted idempotent response."""

    body: dict[str, Any]
    status_code: int
    fingerprint: str | None


class IdempotencyRepo(Protocol):
    """Persistence port. DB-backed impl lives in infrastructure layer."""

    async def acquire_lock(self, storage_key: str) -> None:
        """Postgres advisory lock — released at txn end."""
        ...

    async def lookup(self, storage_key: str) -> CachedResponse | None: ...

    async def store(
        self,
        storage_key: str,
        cached: CachedResponse,
        expires_at: datetime,
    ) -> None: ...


class IdempotencyConflict(Exception):
    """Same key, different request body -> 409 Conflict (RFC draft §2.4)."""

    def __init__(self, storage_key: str) -> None:
        super().__init__(f"idempotency_body_mismatch:{storage_key}")
        self.storage_key = storage_key


async def replay_or_remember(
    *,
    request: Request,
    repo: IdempotencyRepo,
    user_id: str | None,
    raw_key: str,
    body: bytes,
) -> CachedResponse | None:
    """Return cached response on hit, ``None`` on miss.

    Caller (typically a FastAPI dependency) is responsible for:
        1. Calling this before handler dispatch.
        2. If ``None``: invoking the handler, then calling :func:`remember`.
        3. If a `CachedResponse`: returning it as the HTTP response.

    Raises :class:`IdempotencyConflict` when the same key was used with
    a different body (handler MUST NOT re-run; return 409).
    """
    validate_idempotency_key(raw_key)
    skey = storage_key(user_id, request.url.path, raw_key)
    await repo.acquire_lock(skey)
    cached = await repo.lookup(skey)
    if cached is None:
        return None
    fp = fingerprint_body(body)
    if cached.fingerprint is not None and cached.fingerprint != fp:
        raise IdempotencyConflict(skey)
    return cached


async def remember(
    *,
    request: Request,
    repo: IdempotencyRepo,
    user_id: str | None,
    raw_key: str,
    body: bytes,
    response_body: dict[str, Any],
    status_code: int,
) -> None:
    """Persist a freshly-computed response under (user, path, key) for 24h."""
    skey = storage_key(user_id, request.url.path, raw_key)
    cached = CachedResponse(
        body=response_body,
        status_code=status_code,
        fingerprint=fingerprint_body(body),
    )
    expires = datetime.now(UTC) + IDEMPOTENCY_TTL
    await repo.store(skey, cached, expires)


def cached_to_response(cached: CachedResponse) -> JSONResponse:
    """Materialise a CachedResponse as a JSONResponse for replay."""
    return JSONResponse(status_code=cached.status_code, content=cached.body)


def require_idempotency_key(value: str | None) -> str:
    """Hard-require ``Idempotency-Key`` header.

    Used by routers where the header is mandatory (POST /plans,
    POST /logs/food/text). Raises :class:`ValidationError` with detail
    ``idempotency_key_required`` (missing) or ``idempotency_key_invalid_uuid4``
    (malformed) — both map to HTTP 422.
    """
    if not value:
        raise ValidationError("idempotency_key_required", field="Idempotency-Key")
    return validate_idempotency_key(value)


async def lookup_redis(
    *,
    redis: Any,
    user_id: str,
    path: str,
    raw_key: str,
    body: bytes,
) -> tuple[str, CachedResponse | None]:
    """Redis-backed idempotency lookup.

    Returns ``(storage_key, cached_or_None)``. The caller MUST short-circuit
    with the cached response on a hit, or proceed with the handler on miss
    and call :func:`remember_redis` after a successful response.

    Raises:
        IdempotencyConflict: same key, different body fingerprint.
        ValidationError: malformed ``raw_key``.
    """
    validate_idempotency_key(raw_key)
    skey = storage_key(user_id, path, raw_key)
    raw = await redis.get(skey)
    if raw is None:
        return skey, None
    data = json.loads(raw if isinstance(raw, str) else raw.decode())
    fp = fingerprint_body(body)
    if data.get("fingerprint") and data["fingerprint"] != fp:
        raise IdempotencyConflict(skey)
    cached = CachedResponse(
        body=data.get("body", {}),
        status_code=int(data.get("status_code", 200)),
        fingerprint=data.get("fingerprint"),
    )
    return skey, cached


async def remember_redis(
    *,
    redis: Any,
    storage_key: str,
    body: bytes,
    response_body: dict[str, Any],
    status_code: int,
) -> None:
    """Persist a freshly computed response under ``storage_key`` for 24h."""
    payload = json.dumps(
        {
            "body": response_body,
            "status_code": status_code,
            "fingerprint": fingerprint_body(body),
        }
    )
    await redis.set(storage_key, payload, ex=int(IDEMPOTENCY_TTL.total_seconds()))


__all__ = [
    "CachedResponse",
    "IDEMPOTENCY_TTL",
    "IdempotencyConflict",
    "IdempotencyRepo",
    "cached_to_response",
    "fingerprint_body",
    "lookup_redis",
    "remember",
    "remember_redis",
    "replay_or_remember",
    "require_idempotency_key",
    "storage_key",
    "validate_idempotency_key",
]


# --- Reference SQL repo (kept here for discoverability; thin enough that
# splitting into an infrastructure module yields no benefit) ---


class SqlIdempotencyRepo:
    """Postgres-backed :class:`IdempotencyRepo`.

    Uses the `idempotency_keys` table (migration 0007). Concurrent
    serialisation via ``pg_advisory_xact_lock`` — lock is released on
    txn commit/rollback, no leak risk.
    """

    def __init__(self, session: Any) -> None:  # AsyncSession — typed Any to keep
        self._session = session  # this module SQLAlchemy-free for mypy isolation

    async def acquire_lock(self, storage_key: str) -> None:
        from sqlalchemy import text  # local import — keeps top-level mypy clean

        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
            {"k": storage_key},
        )

    async def lookup(self, storage_key: str) -> CachedResponse | None:
        from sqlalchemy import text

        row = (
            await self._session.execute(
                text(
                    "SELECT response_body FROM idempotency_keys "
                    "WHERE key = :k AND expires_at > now()"
                ),
                {"k": storage_key},
            )
        ).first()
        if row is None:
            return None
        raw = row[0]
        data: dict[str, Any] = raw if isinstance(raw, dict) else json.loads(raw)
        return CachedResponse(
            body=data.get("body", {}),
            status_code=int(data.get("status_code", 200)),
            fingerprint=data.get("fingerprint"),
        )

    async def store(
        self,
        storage_key: str,
        cached: CachedResponse,
        expires_at: datetime,
    ) -> None:
        from sqlalchemy import text

        payload = json.dumps(
            {
                "body": cached.body,
                "status_code": cached.status_code,
                "fingerprint": cached.fingerprint,
            }
        )
        await self._session.execute(
            text(
                "INSERT INTO idempotency_keys (key, response_body, expires_at) "
                "VALUES (:k, CAST(:b AS jsonb), :e) "
                "ON CONFLICT (key) DO NOTHING"
            ),
            {"k": storage_key, "b": payload, "e": expires_at},
        )
