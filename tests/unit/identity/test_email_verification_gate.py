"""Affirmative tests for the email-verification security gate.

QA finding F9 (review 2026-06-07): the email-verification enforcement
shipped without tests asserting the new contract. These tests close
that gap.

Coverage:
 1. RegisterUser dispatches OTP via send_otp (purpose=register).
 2. RegisterUser swallows Resend failure + keeps the registration pending.
 3. VerifyOtp register flow creates the user only after successful OTP.
 4. LoginUser rejects unverified user with the SAME error code as
    wrong password (F2 — no enumeration oracle).
 5. RefreshTokens rejects unverified user (F7 — uniform gate).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.core.errors import InvalidCredentials, Unauthenticated
from app.shared.domain.email_sender import EmailDeliveryError
from app.core.event_bus import EventBus
from app.identity.application.use_cases import (
    LoginUser,
    RefreshTokens,
    RegisterUser,
    VerifyOtp,
)
from app.identity.domain.entities import OtpCode, OtpPurpose, RefreshToken, User


@dataclass
class _UserRepo:
    user: User | None = None

    async def get_by_id(self, user_id: UUID) -> User | None:
        return self.user

    async def get_by_email(self, email: str) -> User | None:
        return self.user if self.user and self.user.email == email else None

    async def get_by_oauth(self, provider: str, subject: str) -> User | None: ...
    async def add(self, user: User) -> None:
        self.user = user

    async def update(self, user: User) -> None:
        self.user = user

    async def schedule_deletion(self, user_id: UUID, scheduled_for: datetime) -> None: ...
    async def cancel_deletion(self, user_id: UUID) -> None: ...
    async def hard_delete(self, user_id: UUID) -> None: ...
    async def get_onboarding_completed(self, user_id: UUID) -> bool:
        return False


@dataclass
class _RefreshRepo:
    added: list[RefreshToken] = field(default_factory=list)
    by_hash: dict[str, RefreshToken] = field(default_factory=dict)

    async def add(self, token: RefreshToken) -> None:
        self.added.append(token)
        self.by_hash[token.token_hash] = token

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        return self.by_hash.get(token_hash)

    async def revoke(self, token_id: UUID, at: datetime) -> None: ...
    async def revoke_family(self, family_id: UUID, at: datetime) -> int:
        return 0

    async def mark_reused(self, token_id: UUID, at: datetime) -> None: ...

    async def lock_for_rotation(self, token_hash: str) -> None: ...


class _Hasher:
    def hash(self, plain: str) -> str:
        return f"argon$:{plain}"

    def verify(self, plain: str, hashed: str) -> bool:
        return hashed == f"argon$:{plain}"


class _Jwt:
    def __init__(self) -> None:
        self._counter = 0

    def sign_access(self, *, user_id: UUID, role: str) -> str:
        return f"access:{user_id}:{role}"

    def sign_refresh_value(self) -> str:
        self._counter += 1
        return f"refresh:{self._counter}"

    def hash_refresh(self, plain: str) -> str:
        return f"hash:{plain}"

    async def verify_access(self, token: str) -> dict:  # type: ignore[type-arg]
        return {}


@dataclass
class _SpySendOtp:
    """Records every dispatch call. Raises on demand for failure-mode tests."""

    calls: list[tuple[str, str]] = field(default_factory=list)
    raises: Exception | None = None

    async def __call__(
        self,
        *,
        email: str,
        purpose: OtpPurpose,
        password_hash: str | None = None,
    ) -> str:
        self.calls.append((email, purpose))
        if self.raises is not None:
            raise self.raises
        return "123456"


def _bus() -> EventBus:
    return EventBus()


def _verified_user(email: str = "miguel@example.com") -> User:
    return User(
        id=uuid4(),
        email=email,
        password_hash="argon$:correctsecret",  # noqa: S106 — test fixture
        oauth_provider=None,
        oauth_subject=None,
        email_verified=True,
        role="user",
        created_at=datetime.now(UTC),
    )


def _unverified_user(email: str = "miguel@example.com") -> User:
    u = _verified_user(email)
    u.email_verified = False
    return u


@pytest.mark.asyncio
async def test_register_dispatches_otp_with_register_purpose() -> None:
    repo = _UserRepo()
    spy = _SpySendOtp()
    uc = RegisterUser(
        users=repo,
        refresh_tokens=_RefreshRepo(),
        hasher=_Hasher(),
        jwt=_Jwt(),
        bus=_bus(),
        send_otp=spy,
    )

    await uc(email="new@example.com", password="correctsecret")  # noqa: S106

    assert spy.calls == [("new@example.com", "register")]
    assert repo.user is None


@dataclass
class _FakeRegisterOtpRepo:
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


@pytest.mark.asyncio
async def test_verify_otp_register_creates_user_on_pending_registration() -> None:
    repo = _UserRepo()
    hasher = _Hasher()
    otp_repo = _FakeRegisterOtpRepo()
    otp_repo.active = OtpCode(
        id=uuid4(),
        user_id=None,
        email="new@example.com",
        password_hash=hasher.hash("correctsecret"),
        code_hash=hasher.hash("123456"),
        purpose="register",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    uc = VerifyOtp(
        users=repo,
        otps=otp_repo,
        refresh_tokens=_RefreshRepo(),
        hasher=hasher,
        jwt=_Jwt(),
        bus=_bus(),
    )

    pair = await uc(email="new@example.com", purpose="register", code="123456")

    assert pair.user_id == repo.user.id  # type: ignore[union-attr]
    assert repo.user is not None
    assert repo.user.email_verified is True


@pytest.mark.asyncio
async def test_register_swallows_email_delivery_failure_and_keeps_pending_verification() -> None:
    """Resend down must NOT fail registration. The pending OTP can be retried
    via POST /auth/otp/send.

    Contract narrowed (2026-06-09): we swallow ONLY ``EmailDeliveryError``.
    Any other exception (SQL, type bug) must propagate so the route-level
    session rollback runs — otherwise the session sits in
    ``InFailedSqlTransaction`` and the request 500s at commit time.
    """
    repo = _UserRepo()
    spy = _SpySendOtp(raises=EmailDeliveryError("email_provider_status_503"))
    uc = RegisterUser(
        users=repo,
        refresh_tokens=_RefreshRepo(),
        hasher=_Hasher(),
        jwt=_Jwt(),
        bus=_bus(),
        send_otp=spy,
    )

    await uc(email="new@example.com", password="correctsecret")  # noqa: S106

    assert spy.calls == [("new@example.com", "register")]
    # No user is created before OTP verification.
    assert repo.user is None


@pytest.mark.asyncio
async def test_register_propagates_non_email_failures() -> None:
    """Persistence / unexpected errors MUST propagate. Previously a bare
    ``except Exception`` swallowed DB errors and left the SQLAlchemy session
    in a failed transaction, which surfaced as an opaque HTTP 500 at commit
    time. Root cause of the 500-on-register bug fixed on 2026-06-09."""
    repo = _UserRepo()
    spy = _SpySendOtp(raises=RuntimeError("simulated_db_failure"))
    uc = RegisterUser(
        users=repo,
        refresh_tokens=_RefreshRepo(),
        hasher=_Hasher(),
        jwt=_Jwt(),
        bus=_bus(),
        send_otp=spy,
    )

    with pytest.raises(RuntimeError):
        await uc(email="new@example.com", password="correctsecret")  # noqa: S106
    assert repo.user is None


@pytest.mark.asyncio
async def test_login_rejects_unverified_user_with_same_code_as_wrong_password() -> None:
    """QA F2: do not distinguish 'unverified' from 'invalid_credentials' at
    the login surface. Both must raise the same error code so an attacker
    cannot use the response to confirm a valid email+password pair."""
    repo = _UserRepo(user=_unverified_user())
    uc = LoginUser(
        users=repo,
        refresh_tokens=_RefreshRepo(),
        hasher=_Hasher(),
        jwt=_Jwt(),
        bus=_bus(),
    )

    with pytest.raises(InvalidCredentials) as exc:
        await uc(email="miguel@example.com", password="correctsecret")  # noqa: S106

    # Same detail string as a wrong-password attempt — no oracle.
    assert exc.value.detail == "invalid_credentials"


@pytest.mark.asyncio
async def test_login_accepts_user_after_verification() -> None:
    repo = _UserRepo(user=_verified_user())
    uc = LoginUser(
        users=repo,
        refresh_tokens=_RefreshRepo(),
        hasher=_Hasher(),
        jwt=_Jwt(),
        bus=_bus(),
    )

    pair = await uc(email="miguel@example.com", password="correctsecret")  # noqa: S106

    assert pair.user_id == repo.user.id  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_refresh_rejects_unverified_user() -> None:
    """QA F7: uniform email-verification gate. A refresh token issued at
    register before OTP verify cannot rotate into a fresh access token —
    otherwise the bearer would be valid indefinitely despite get_current_user
    rejecting every protected call."""
    user = _unverified_user()
    repo = _UserRepo(user=user)
    refresh_repo = _RefreshRepo()
    jwt = _Jwt()

    plain = jwt.sign_refresh_value()
    token = RefreshToken(
        id=uuid4(),
        user_id=user.id,
        token_hash=jwt.hash_refresh(plain),
        family_id=uuid4(),
        parent_id=None,
        expires_at=datetime.now(UTC) + timedelta(days=30),
        created_at=datetime.now(UTC),
    )
    await refresh_repo.add(token)

    uc = RefreshTokens(
        users=repo,
        refresh_tokens=refresh_repo,
        jwt=jwt,
        bus=_bus(),
    )

    with pytest.raises(Unauthenticated) as exc:
        await uc(refresh_plain=plain)

    assert exc.value.detail == "email_not_verified"
