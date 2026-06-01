# P0 Pre-Launch Hardening — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close 4 P0 blockers before production launch — MercadoPago HMAC validation, idempotency DB fallback, jose→pyjwt migration, Sentry activation.

**Architecture:** Surgical fixes to existing modules. No new bounded contexts. Maintain Clean Architecture boundaries — domain untouched, infrastructure adapters swap, presentation glue added.

**Tech Stack:** Python 3.12, FastAPI 0.115, SQLAlchemy 2.0 async, Redis, Postgres, PyJWT, Sentry SDK.

---

## File Structure

**New:**
- `migrations/versions/0007_idempotency_keys.py` — DB fallback table for idempotency.
- `app/core/sentry.py` — Sentry init + before_send PII scrubber.
- `tests/unit/test_mercadopago_webhook_hmac.py`
- `tests/unit/test_idempotency_db_fallback.py`
- `tests/unit/test_jwt_pyjwt_equivalence.py`
- `tests/unit/test_sentry_init.py`

**Modified:**
- `app/billing/gateways.py` — implement `MercadoPagoGateway.verify_webhook` with HMAC SHA-256.
- `app/identity/presentation/dependencies.py` — `idempotency_key` falls back to DB when Redis miss.
- `app/identity/infrastructure/jwt_signer.py` — swap `python-jose` for `PyJWT`.
- `app/main.py` — call `init_sentry()` at startup.
- `app/core/config.py` — add `mercadopago_webhook_secret`, `sentry_environment`, `sentry_traces_sample_rate`.
- `pyproject.toml` — remove `python-jose`, add `pyjwt[crypto]>=2.10`, add `sentry-sdk[fastapi]` (already present).

---

## Task 1: PyJWT migration (lowest risk, isolated)

**Files:**
- Modify: `app/identity/infrastructure/jwt_signer.py`
- Modify: `pyproject.toml`
- Test: `tests/unit/test_jwt_pyjwt_equivalence.py`

- [ ] **Step 1: Failing equivalence test**

```python
# tests/unit/test_jwt_pyjwt_equivalence.py
"""PyJWT signer round-trip + claims contract."""
from __future__ import annotations

import tempfile
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


@pytest.fixture
def keypair(monkeypatch, tmp_path):
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    priv_path = tmp_path / "jwt.pem"
    pub_path = tmp_path / "jwt.pub"
    priv_path.write_bytes(priv_pem)
    pub_path.write_bytes(pub_pem)
    monkeypatch.setenv("JWT_PRIVATE_KEY_PATH", str(priv_path))
    monkeypatch.setenv("JWT_PUBLIC_KEY_PATH", str(pub_path))
    # invalidate cached settings
    from app.core.config import get_settings
    get_settings.cache_clear()
    yield


def test_sign_and_verify_access(keypair):
    from app.identity.infrastructure.jwt_signer import JwtSigner
    signer = JwtSigner()
    uid = uuid4()
    token = signer.sign_access(user_id=uid, role="user")
    claims = signer.verify_access(token)
    assert claims["sub"] == str(uid)
    assert claims["role"] == "user"
    assert claims["iss"] == "nova-nutrition"
    assert claims["aud"] == "nova-mobile"


def test_verify_rejects_tampered(keypair):
    from app.identity.infrastructure.jwt_signer import JwtSigner
    from app.core.errors import Unauthenticated
    signer = JwtSigner()
    token = signer.sign_access(user_id=uuid4(), role="user")
    # flip a byte in the signature
    head, payload, sig = token.split(".")
    bad = f"{head}.{payload}.{sig[:-2]}AA"
    with pytest.raises(Unauthenticated):
        signer.verify_access(bad)


def test_verify_rejects_wrong_audience(keypair, monkeypatch):
    from app.identity.infrastructure.jwt_signer import JwtSigner
    from app.core.errors import Unauthenticated
    signer = JwtSigner()
    token = signer.sign_access(user_id=uuid4(), role="user")
    monkeypatch.setattr(signer, "_audience", "wrong-audience")
    with pytest.raises(Unauthenticated):
        signer.verify_access(token)
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `pytest tests/unit/test_jwt_pyjwt_equivalence.py -v`
Expected: tests fail or pass under jose; goal is parity after swap.

- [ ] **Step 3: Update deps**

Edit `pyproject.toml`:

```toml
# REMOVE:
    "python-jose[cryptography]>=3.3,<4",
# ADD:
    "pyjwt[crypto]>=2.10,<3",
```

Also in `[project.optional-dependencies].dev` REMOVE `types-python-jose`.

Run: `pip install -e .[dev]`

- [ ] **Step 4: Rewrite `jwt_signer.py`**

Replace `jose_jwt` calls with PyJWT:

```python
# app/identity/infrastructure/jwt_signer.py
"""RS256 JWT signer/verifier backed by PyJWT.

Migrated from python-jose (2026-06): jose is semi-abandoned and accrues
CVEs. PyJWT is the mainstream maintained alternative; same RS256 keys
work without rotation.
"""
from __future__ import annotations

import hashlib
import secrets
import time
from pathlib import Path
from uuid import UUID, uuid4

import jwt as pyjwt
from jwt.exceptions import InvalidTokenError

from app.core.config import get_settings
from app.core.errors import Unauthenticated


class JwtSigner:
    def __init__(self) -> None:
        s = get_settings()
        self._issuer = s.jwt_issuer
        self._audience = s.jwt_audience
        self._access_ttl = s.jwt_access_ttl_seconds
        priv_path = Path(s.jwt_private_key_path)
        pub_path = Path(s.jwt_public_key_path)
        self._private_key = priv_path.read_bytes() if priv_path.exists() else b""
        self._public_key = pub_path.read_bytes() if pub_path.exists() else b""

    def sign_access(self, *, user_id: UUID, role: str) -> str:
        now = int(time.time())
        payload = {
            "sub": str(user_id),
            "role": role,
            "iss": self._issuer,
            "aud": self._audience,
            "iat": now,
            "exp": now + self._access_ttl,
            "jti": uuid4().hex,
        }
        return pyjwt.encode(payload, self._private_key, algorithm="RS256")

    def verify_access(self, token: str) -> dict:
        try:
            return pyjwt.decode(
                token,
                self._public_key,
                algorithms=["RS256"],
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ["exp", "iat", "sub", "aud", "iss"]},
            )
        except InvalidTokenError as e:
            raise Unauthenticated(f"jwt_invalid:{e!s}") from e

    @staticmethod
    def sign_refresh_value() -> str:
        return secrets.token_urlsafe(48)

    @staticmethod
    def hash_refresh(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()
```

- [ ] **Step 5: Run tests — verify they pass**

Run: `pytest tests/unit/test_jwt_pyjwt_equivalence.py tests/ -k "jwt or identity" -v`
Expected: all pass.

- [ ] **Step 6: Verify no leftover jose imports**

Run: `grep -rn "from jose\|import jose" app/ tests/ 2>/dev/null`
Expected: empty output.

- [ ] **Step 7: Commit**

```bash
git add app/identity/infrastructure/jwt_signer.py pyproject.toml tests/unit/test_jwt_pyjwt_equivalence.py
git commit -m "refactor(auth): swap python-jose for PyJWT (jose semi-abandoned, CVE risk)"
```

---

## Task 2: Sentry activation

**Files:**
- Create: `app/core/sentry.py`
- Modify: `app/main.py`
- Modify: `app/core/config.py`
- Test: `tests/unit/test_sentry_init.py`

- [ ] **Step 1: Config**

Edit `app/core/config.py` Settings:

```python
    sentry_dsn: str = ""
    sentry_environment: str = "production"
    sentry_traces_sample_rate: float = 0.10
    sentry_profiles_sample_rate: float = 0.0
```

- [ ] **Step 2: Failing test**

```python
# tests/unit/test_sentry_init.py
from unittest.mock import patch

from app.core.sentry import init_sentry, scrub_pii


def test_init_skips_when_dsn_empty(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "")
    from app.core.config import get_settings
    get_settings.cache_clear()
    with patch("sentry_sdk.init") as mock_init:
        init_sentry()
        mock_init.assert_not_called()


def test_init_calls_sdk_when_dsn_set(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "https://x@sentry.io/1")
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "staging")
    from app.core.config import get_settings
    get_settings.cache_clear()
    with patch("sentry_sdk.init") as mock_init:
        init_sentry()
        mock_init.assert_called_once()
        kwargs = mock_init.call_args.kwargs
        assert kwargs["dsn"] == "https://x@sentry.io/1"
        assert kwargs["environment"] == "staging"
        assert callable(kwargs["before_send"])


def test_scrub_strips_authorization_header():
    event = {"request": {"headers": {"authorization": "Bearer abc123", "x-other": "ok"}}}
    out = scrub_pii(event, hint={})
    assert out["request"]["headers"]["authorization"] == "[Filtered]"
    assert out["request"]["headers"]["x-other"] == "ok"


def test_scrub_strips_email_from_user():
    event = {"user": {"id": "u-1", "email": "x@y.com", "ip_address": "1.2.3.4"}}
    out = scrub_pii(event, hint={})
    assert "email" not in out["user"]
    assert "ip_address" not in out["user"]
    assert out["user"]["id"] == "u-1"
```

- [ ] **Step 3: Run test — verify failure**

Run: `pytest tests/unit/test_sentry_init.py -v`
Expected: ImportError on `app.core.sentry`.

- [ ] **Step 4: Implement `app/core/sentry.py`**

```python
# app/core/sentry.py
"""Sentry initialiser + PII scrubber.

Disabled by default (empty DSN). Production opt-in via SENTRY_DSN env.
Strips: Authorization headers, cookies, user emails, IPs, and any
body field whose key matches PII_KEYS. Vision-detected food names
already excluded from logs (ADR-0003); event payloads here scrubbed
defensively in case other contexts leak them.
"""
from __future__ import annotations

from typing import Any

import sentry_sdk
from sentry_sdk.integrations.asyncio import AsyncioIntegration
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

from app.core.config import get_settings

_SENSITIVE_HEADERS = {"authorization", "cookie", "x-api-key", "idempotency-key"}
_PII_USER_KEYS = {"email", "ip_address", "username"}


def scrub_pii(event: dict, hint: dict) -> dict | None:
    req = event.get("request") or {}
    headers = req.get("headers")
    if isinstance(headers, dict):
        for k in list(headers.keys()):
            if k.lower() in _SENSITIVE_HEADERS:
                headers[k] = "[Filtered]"
    user = event.get("user")
    if isinstance(user, dict):
        for k in _PII_USER_KEYS:
            user.pop(k, None)
    return event


def init_sentry() -> None:
    s = get_settings()
    if not s.sentry_dsn:
        return
    sentry_sdk.init(
        dsn=s.sentry_dsn,
        environment=s.sentry_environment,
        traces_sample_rate=s.sentry_traces_sample_rate,
        profiles_sample_rate=s.sentry_profiles_sample_rate,
        send_default_pii=False,
        before_send=scrub_pii,
        integrations=[
            FastApiIntegration(transaction_style="endpoint"),
            SqlalchemyIntegration(),
            AsyncioIntegration(),
        ],
    )
```

- [ ] **Step 5: Wire in `app/main.py`**

Add **before** FastAPI app instantiation:

```python
from app.core.sentry import init_sentry

init_sentry()
```

- [ ] **Step 6: Run tests — verify pass**

Run: `pytest tests/unit/test_sentry_init.py -v`
Expected: 4 passed.

- [ ] **Step 7: Commit**

```bash
git add app/core/sentry.py app/main.py app/core/config.py tests/unit/test_sentry_init.py
git commit -m "feat(observability): activate Sentry with PII scrubber + integration set"
```

---

## Task 3: Idempotency DB fallback

**Files:**
- Create: `migrations/versions/0007_idempotency_keys.py`
- Modify: `app/identity/presentation/dependencies.py` (`idempotency_key` + `remember_idempotent`)
- Test: `tests/unit/test_idempotency_db_fallback.py`

- [ ] **Step 1: Migration**

```python
# migrations/versions/0007_idempotency_keys.py
"""idempotency_keys table — DB fallback when Redis is cold/restarted"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "idempotency_keys",
        sa.Column("key", sa.Text, primary_key=True),
        sa.Column("response_body", sa.JSON, nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
    )
    op.create_index(
        "idx_idempotency_keys_expires_at",
        "idempotency_keys", ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_idempotency_keys_expires_at", table_name="idempotency_keys")
    op.drop_table("idempotency_keys")
```

Verify locally: `alembic upgrade head` succeeds against dev DB.

- [ ] **Step 2: Failing test**

```python
# tests/unit/test_idempotency_db_fallback.py
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from app.identity.presentation.dependencies import (
    db_lookup_idempotent,
    remember_idempotent,
)


async def test_db_lookup_returns_cached_body(fake_session):
    fake_session.execute.return_value.first.return_value = (
        {"ok": True, "n": 1},
    )
    body = await db_lookup_idempotent(fake_session, "idem:abc")
    assert body == {"ok": True, "n": 1}


async def test_db_lookup_returns_none_when_missing(fake_session):
    fake_session.execute.return_value.first.return_value = None
    body = await db_lookup_idempotent(fake_session, "idem:miss")
    assert body is None


async def test_remember_writes_to_redis_and_db(fake_redis, fake_session):
    await remember_idempotent("idem:xyz", {"n": 2}, session=fake_session, redis=fake_redis)
    raw = await fake_redis.get("idem:xyz")
    assert json.loads(raw) == {"n": 2}
    fake_session.execute.assert_awaited()  # INSERT ... ON CONFLICT DO NOTHING


@pytest.fixture
def fake_session():
    s = AsyncMock()
    s.execute.return_value = AsyncMock()
    return s
```

Ensure `tests/conftest.py` has the `fake_redis` fixture (added in earlier vision plan; if absent, add):

```python
@pytest.fixture
async def fake_redis():
    import fakeredis.aioredis
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield client
    await client.aclose()
```

Add `fakeredis>=2.26,<3` to `pyproject.toml` `[project.optional-dependencies].dev` if missing.

- [ ] **Step 3: Run test — verify failure**

Run: `pytest tests/unit/test_idempotency_db_fallback.py -v`
Expected: ImportError on `db_lookup_idempotent`.

- [ ] **Step 4: Implement fallback in `dependencies.py`**

Edit `app/identity/presentation/dependencies.py`. Replace `idempotency_key` and `remember_idempotent`:

```python
from datetime import datetime, timedelta, timezone

from sqlalchemy import text


async def db_lookup_idempotent(session: AsyncSession, rkey: str) -> dict | None:
    row = (await session.execute(text(
        "SELECT response_body FROM idempotency_keys "
        "WHERE key = :k AND expires_at > now()"
    ), {"k": rkey})).first()
    if row is None:
        return None
    body = row[0]
    return body if isinstance(body, dict) else json.loads(body)


async def idempotency_key(
    request: Request,
    session: SessionDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    user_id: CurrentUserDep | None = None,  # type: ignore[assignment]
) -> tuple[str, str] | None:
    if not idempotency_key:
        return None
    redis = get_redis()
    import hashlib
    composite = f"{user_id}:{request.url.path}:{idempotency_key}"
    rkey = "idem:" + hashlib.sha256(composite.encode()).hexdigest()
    cached = await redis.get(rkey)
    if cached:
        return (rkey, cached)
    # Redis miss → fall through to DB (handles Redis restart / eviction).
    body = await db_lookup_idempotent(session, rkey)
    if body is not None:
        # Warm Redis back up.
        await redis.set(rkey, json.dumps(body), ex=24 * 3600)
        return (rkey, json.dumps(body))
    return (rkey, "")


async def remember_idempotent(
    rkey: str, body: dict, *,
    session: AsyncSession, redis=None,
) -> None:
    r = redis or get_redis()
    payload = json.dumps(body)
    expires = datetime.now(timezone.utc) + timedelta(hours=24)
    await r.set(rkey, payload, ex=24 * 3600)
    await session.execute(text("""
        INSERT INTO idempotency_keys (key, response_body, expires_at)
        VALUES (:k, CAST(:b AS jsonb), :e)
        ON CONFLICT (key) DO NOTHING
    """), {"k": rkey, "b": payload, "e": expires})
```

- [ ] **Step 5: Update callers of `remember_idempotent`**

Run: `grep -rn "remember_idempotent" app/` — pass the active session at each call site. Touch every router that uses it (likely identity, billing, vision presentation). Each caller already has a session dep; pass it through.

If a caller does not have a session dep yet (e.g. notification ack), add `session: SessionDep` to the route signature and forward.

- [ ] **Step 6: Run tests — verify pass**

Run: `pytest tests/unit/test_idempotency_db_fallback.py tests/ -k "idempot" -v`
Expected: all pass.

- [ ] **Step 7: Add cleanup job**

Add to `worker/main.py` cron tasks (or wherever Arq cron lives):

```python
async def cleanup_idempotency_keys(ctx) -> int:
    async with session_scope() as session:
        from sqlalchemy import text
        res = await session.execute(text(
            "DELETE FROM idempotency_keys WHERE expires_at < now()"
        ))
        return res.rowcount
```

Register it on a daily schedule (03:00 UTC) following the existing cron pattern in the file. If no cron pattern exists, leave it as a manual task and add a TODO in `docs/ops/`.

- [ ] **Step 8: Commit**

```bash
git add migrations/versions/0007_idempotency_keys.py \
        app/identity/presentation/dependencies.py \
        tests/unit/test_idempotency_db_fallback.py \
        worker/main.py pyproject.toml tests/conftest.py
git commit -m "feat(idempotency): DB fallback for Idempotency-Key (survives Redis restart)"
```

---

## Task 4: MercadoPago HMAC validation

**Files:**
- Modify: `app/billing/gateways.py` (`MercadoPagoGateway.verify_webhook`)
- Modify: `app/core/config.py` (add secret)
- Test: `tests/unit/test_mercadopago_webhook_hmac.py`

**MP signature spec:** Header `x-signature: ts=<unix_ts>,v1=<hex_sha256>`. Header `x-request-id` is also part of signed payload. The signed string is `id:<data_id>;request-id:<x-request-id>;ts:<ts>;` (per Mercado Pago official docs). HMAC SHA-256 with the webhook secret.

- [ ] **Step 1: Config**

Edit `app/core/config.py`:

```python
    mercadopago_webhook_secret: str = ""
```

- [ ] **Step 2: Failing test**

```python
# tests/unit/test_mercadopago_webhook_hmac.py
import hashlib
import hmac
import json
import time

import pytest

from app.billing.gateways import MercadoPagoGateway
from app.core.errors import UpstreamError


def _sign(secret: str, data_id: str, request_id: str, ts: str) -> str:
    manifest = f"id:{data_id};request-id:{request_id};ts:{ts};"
    return hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()


@pytest.fixture
def gw(monkeypatch):
    monkeypatch.setenv("MERCADOPAGO_WEBHOOK_SECRET", "supersecret")
    from app.core.config import get_settings
    get_settings.cache_clear()
    return MercadoPagoGateway()


async def test_valid_signature_accepted(gw):
    ts = str(int(time.time()))
    data_id = "12345"
    rid = "req-abc"
    sig_hex = _sign("supersecret", data_id, rid, ts)
    payload = json.dumps({"data": {"id": data_id}, "type": "payment"}).encode()
    out = await gw.verify_webhook(
        payload=payload,
        signature=f"ts={ts},v1={sig_hex}",
        request_id=rid,
    )
    assert out["data"]["id"] == data_id


async def test_tampered_signature_rejected(gw):
    ts = str(int(time.time()))
    payload = json.dumps({"data": {"id": "1"}}).encode()
    with pytest.raises(UpstreamError, match="mercadopago_webhook_invalid"):
        await gw.verify_webhook(
            payload=payload,
            signature=f"ts={ts},v1=deadbeef",
            request_id="r1",
        )


async def test_stale_timestamp_rejected(gw):
    old_ts = str(int(time.time()) - 600)  # 10 min ago
    data_id = "1"; rid = "r"
    sig = _sign("supersecret", data_id, rid, old_ts)
    payload = json.dumps({"data": {"id": data_id}}).encode()
    with pytest.raises(UpstreamError, match="stale"):
        await gw.verify_webhook(
            payload=payload,
            signature=f"ts={old_ts},v1={sig}",
            request_id=rid,
        )


async def test_missing_secret_rejects_all(monkeypatch):
    monkeypatch.setenv("MERCADOPAGO_WEBHOOK_SECRET", "")
    from app.core.config import get_settings
    get_settings.cache_clear()
    gw = MercadoPagoGateway()
    with pytest.raises(UpstreamError, match="secret_not_configured"):
        await gw.verify_webhook(payload=b"{}", signature="ts=1,v1=x", request_id="r")
```

- [ ] **Step 3: Run test — verify failure**

Run: `pytest tests/unit/test_mercadopago_webhook_hmac.py -v`
Expected: signature param missing / always-accepts behaviour.

- [ ] **Step 4: Implement HMAC verify**

Edit `app/billing/gateways.py`:

```python
import hashlib
import hmac
import json
import time

# replace existing MercadoPagoGateway.verify_webhook
    async def verify_webhook(
        self, *, payload: bytes, signature: str, request_id: str = "",
    ) -> dict:
        secret = get_settings().mercadopago_webhook_secret
        if not secret:
            raise UpstreamError("mercadopago_webhook_invalid:secret_not_configured")
        if not signature:
            raise UpstreamError("mercadopago_webhook_invalid:missing_signature")

        parts = dict(p.split("=", 1) for p in signature.split(",") if "=" in p)
        ts = parts.get("ts", "")
        v1 = parts.get("v1", "")
        if not ts or not v1:
            raise UpstreamError("mercadopago_webhook_invalid:malformed_signature")

        # Replay protection: reject events older than 5 minutes.
        try:
            ts_int = int(ts)
        except ValueError:
            raise UpstreamError("mercadopago_webhook_invalid:bad_ts") from None
        if abs(time.time() - ts_int) > 300:
            raise UpstreamError("mercadopago_webhook_invalid:stale_ts")

        try:
            body = json.loads(payload.decode())
        except Exception as e:
            raise UpstreamError("mercadopago_webhook_invalid:bad_payload") from e

        data_id = str(((body.get("data") or {}).get("id")) or "")
        manifest = f"id:{data_id};request-id:{request_id};ts:{ts};"
        expected = hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, v1):
            raise UpstreamError("mercadopago_webhook_invalid:bad_signature")

        return body
```

- [ ] **Step 5: Pass `request_id` from router**

Edit `app/billing/router.py` MP webhook handler — capture `X-Request-Id` header and forward:

```python
@router.post("/webhooks/mercadopago")
async def mercadopago_webhook(
    request: Request,
    x_signature: Annotated[str | None, Header(alias="x-signature")] = None,
    x_request_id: Annotated[str | None, Header(alias="x-request-id")] = None,
    session: SessionDep = ...,
):
    payload = await request.body()
    gw = MercadoPagoGateway()
    event = await gw.verify_webhook(
        payload=payload,
        signature=x_signature or "",
        request_id=x_request_id or "",
    )
    # ... existing dedupe / event-processing logic unchanged ...
```

- [ ] **Step 6: Run tests — verify pass**

Run: `pytest tests/unit/test_mercadopago_webhook_hmac.py tests/ -k "mercadopago or billing" -v`
Expected: all pass.

- [ ] **Step 7: Update runbook**

Append to `docs/ops/` (or create `docs/ops/runbook-mercadopago-webhook.md`) a 3-line note:

> Set `MERCADOPAGO_WEBHOOK_SECRET` in production env. Retrieve from
> Mercado Pago dashboard → Webhooks → Secret. Rotate every 90 days.

- [ ] **Step 8: Commit**

```bash
git add app/billing/gateways.py app/billing/router.py app/core/config.py \
        tests/unit/test_mercadopago_webhook_hmac.py docs/ops/
git commit -m "fix(billing): strict HMAC-SHA256 validation on MercadoPago webhooks"
```

---

## Post-implementation verification

- [ ] **Full test suite:** `pytest tests/ -x --ignore=tests/load` → all green.
- [ ] **Lint:** `ruff check app/ tests/` → zero.
- [ ] **Type check:** `mypy app/` → zero.
- [ ] **Grep dead jose imports:** `grep -rn "jose" app/ tests/ pyproject.toml` → empty.
- [ ] **Migration round-trip:** `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` → clean.

---

## Open decisions

None. All defaults locked in (24h TTL idempotency, 5-min MP replay window, RS256 alg, Sentry 10% traces sample).
