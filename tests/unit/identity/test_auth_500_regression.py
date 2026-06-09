"""Regression suite — every scenario in this file was a potential HTTP 500
in the auth flow before the 2026-06-09 hardening pass. Each test asserts
the failure mode is now mapped to a stable domain error (4xx) or fails
open (rate limit) instead of bubbling as opaque server error.

References: QA audit ``auth-500-elimination`` 2026-06-09.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from redis.exceptions import RedisError
from sqlalchemy.exc import IntegrityError

from app.core.errors import ConflictError
from app.core.event_bus import EventBus
from app.identity.application.use_cases import OAuthLogin, VerifyOtp
from app.identity.domain.entities import OtpCode, OtpPurpose, RefreshToken, User
from app.identity.infrastructure import rate_limit as rl_mod


# ---------------------------------------------------------------------------
# Risk 3 — rate limiter fails OPEN on Redis acquisition failure (not only on
# execute()). Previously only RedisError raised by pipe.execute() was caught;
# a RedisError raised by the get_redis() factory itself bubbled as 500.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limit_fails_open_when_redis_factory_raises(monkeypatch) -> None:
    def _boom():
        raise RedisError("connection_refused")

    monkeypatch.setattr(rl_mod, "get_redis", _boom)

    # Must NOT raise — endpoint stays available during Redis outage.
    await rl_mod.rate_limit(scope="auth", identifier="x@y.z", limit_per_min=10)


@pytest.mark.asyncio
async def test_rate_limit_fails_open_when_redis_factory_raises_generic(monkeypatch) -> None:
    """ConnectionPool can raise non-RedisError subclasses (OSError on DNS
    failure, RuntimeError on shutdown). Fail-open must cover those too."""

    def _boom():
        raise RuntimeError("event_loop_closed")

    monkeypatch.setattr(rl_mod, "get_redis", _boom)

    await rl_mod.rate_limit(scope="auth", identifier="x@y.z", limit_per_min=10)


# ---------------------------------------------------------------------------
# Risk 6 — race condition in VerifyOtp(purpose="register") concurrent INSERT
# Same email verifies twice → UNIQUE violation on users.email → was 500.
# Now mapped to ConflictError (HTTP 409).
# ---------------------------------------------------------------------------


@dataclass
class _RaceUserRepo:
    user: User | None = None

    async def get_by_id(self, user_id: UUID) -> User | None:
        return self.user

    async def get_by_email(self, email: str) -> User | None:
        return self.user

    async def get_by_oauth(self, provider: str, subject: str) -> User | None:
        return None

    async def add(self, user: User) -> None:
        # Simulate UNIQUE constraint violation from the racing insert that
        # already won.
        raise IntegrityError("INSERT", {}, Exception("users_email_unique"))

    async def update(self, user: User) -> None:
        self.user = user

    async def schedule_deletion(self, *a, **k) -> None: ...
    async def cancel_deletion(self, *a, **k) -> None: ...
    async def hard_delete(self, *a, **k) -> None: ...

    async def get_onboarding_completed(self, user_id: UUID) -> bool:
        return False


@dataclass
class _OtpRepo:
    active: OtpCode | None = None

    async def add(self, otp: OtpCode) -> None:
        self.active = otp

    async def get_active(self, user_id: UUID, purpose: OtpPurpose) -> OtpCode | None:
        return self.active

    async def get_active_by_email(self, email: str, purpose: OtpPurpose) -> OtpCode | None:
        return self.active

    async def increment_attempts(self, otp_id: UUID) -> int:
        return 0

    async def lock(self, otp_id: UUID, until: datetime) -> None: ...
    async def consume(self, otp_id: UUID) -> None:
        self.active = None


@dataclass
class _RefreshRepo:
    added: list[RefreshToken] = field(default_factory=list)

    async def add(self, token: RefreshToken) -> None:
        self.added.append(token)

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        return None

    async def revoke(self, *a, **k) -> None: ...
    async def revoke_family(self, *a, **k) -> int:
        return 0

    async def mark_reused(self, *a, **k) -> None: ...


class _Hasher:
    def hash(self, plain: str) -> str:
        return f"argon$:{plain}"

    def verify(self, plain: str, hashed: str) -> bool:
        return hashed == f"argon$:{plain}"


class _Jwt:
    def sign_access(self, *, user_id: UUID, role: str) -> str:
        return "access"

    def sign_refresh_value(self) -> str:
        return "refresh"

    def hash_refresh(self, plain: str) -> str:
        return f"hash:{plain}"

    async def verify_access(self, token: str) -> dict:
        return {}


@pytest.mark.asyncio
async def test_verify_otp_register_maps_unique_violation_to_conflict() -> None:
    """Two concurrent OTP verifies for the same pending email — the loser
    must receive 409, NOT 500."""
    hasher = _Hasher()
    otps = _OtpRepo(
        active=OtpCode(
            id=uuid4(),
            user_id=None,
            email="race@example.com",
            password_hash=hasher.hash("correctsecret"),
            code_hash=hasher.hash("123456"),
            purpose="register",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
    )
    uc = VerifyOtp(
        users=_RaceUserRepo(),  # add() raises IntegrityError
        otps=otps,
        refresh_tokens=_RefreshRepo(),
        hasher=hasher,
        jwt=_Jwt(),
        bus=EventBus(),
    )

    with pytest.raises(ConflictError):
        await uc(email="race@example.com", purpose="register", code="123456")


# ---------------------------------------------------------------------------
# Risk 6b — OAuthLogin races on first-time user creation.
# ---------------------------------------------------------------------------


class _OAuthVerifier:
    async def verify_id_token(self, id_token: str) -> dict:
        return {
            "sub": "google-sub-123",
            "email": "race-oauth@example.com",
            "email_verified": True,
        }


@pytest.mark.asyncio
async def test_oauth_login_maps_unique_violation_to_conflict() -> None:
    uc = OAuthLogin(
        users=_RaceUserRepo(),  # get_by_oauth and get_by_email both → None, add() → IntegrityError
        refresh_tokens=_RefreshRepo(),
        verifier=_OAuthVerifier(),
        jwt=_Jwt(),
        bus=EventBus(),
        provider="google",
    )

    with pytest.raises(ConflictError):
        await uc(id_token="fake-id-token")  # noqa: S106


# ---------------------------------------------------------------------------
# Risk 5 — SqlOtpRepository.add must purge prior active OTP for the same
# (email|user_id, purpose) so successive sends do not accumulate stale rows.
# Tested at the SQL builder layer via a captured-statement spy.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sql_otp_repository_invalidates_prior_active_otp_pending() -> None:
    """Pending registration (user_id is NULL) — prior OTP for same email is
    deleted before INSERT."""
    from app.identity.infrastructure.repositories import SqlOtpRepository

    class _SessSpy:
        def __init__(self) -> None:
            self.executed: list[tuple[str, dict]] = []
            self.added: list[object] = []

        async def execute(self, stmt, params):  # noqa: ANN001
            self.executed.append((str(stmt), params))

            class _R:
                def first(self_inner):  # noqa: N805
                    return None

            return _R()

        def add(self, model: object) -> None:
            self.added.append(model)

        async def flush(self) -> None:
            return None

    sess = _SessSpy()
    repo = SqlOtpRepository(sess)  # type: ignore[arg-type]
    otp = OtpCode(
        id=uuid4(),
        user_id=None,
        email="purge@example.com",
        password_hash="argon$:secret",
        code_hash="argon$:111111",
        purpose="register",
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    await repo.add(otp)
    # First call should be a DELETE on prior pending-registration OTPs.
    assert any("DELETE FROM otp_codes" in s for s, _ in sess.executed), (
        "SqlOtpRepository.add must invalidate prior active OTP rows"
    )
    assert len(sess.added) == 1
