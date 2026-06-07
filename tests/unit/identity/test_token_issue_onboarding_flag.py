"""Verify ``TokenPair.onboarding_completed`` is populated correctly across
every auth use case that issues tokens.

QA finding F-T1 (nova-qa-elite review, 2026-06-06): the original change
that added ``onboarding_completed`` to ``TokenPairResponse`` shipped without
unit tests asserting the new behaviour. These tests close that gap.

Coverage (one assertion per branch that calls ``_issue_token_pair``):
 1. ``RegisterUser`` → flag always ``False`` (no DB lookup performed)
 2. ``LoginUser`` → flag mirrors repository value (``True`` branch)
 3. ``LoginUser`` → flag mirrors repository value (``False`` branch)
 4. ``RefreshTokens`` → flag re-fetched on every rotation (freshness contract)
 5. ``OAuthLogin`` (new user) → flag ``False`` (profile row not yet created)
 6. ``OAuthLogin`` (existing user, onboarded) → flag ``True``
 7. ``VerifyOtp`` purpose=``login`` → flag mirrors repository value
 8. ``VerifyOtp`` purpose=``register`` → flag ``False`` (no profile after register)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.core.event_bus import EventBus
from app.identity.application.use_cases import (
    LoginUser,
    OAuthLogin,
    RefreshTokens,
    RegisterUser,
    VerifyOtp,
)
from app.identity.domain.entities import OtpCode, OtpPurpose, RefreshToken, User

# ---------------------------------------------------------------------------
# Fakes — minimal Protocol implementations
# ---------------------------------------------------------------------------


@dataclass
class _CountingUserRepo:
    """Records how many times ``get_onboarding_completed`` was called.

    The query-count assertion matters for ``RegisterUser`` (must NOT query
    the profile table — flag is hardcoded ``False`` to avoid a wasted round
    trip on brand-new accounts) and for ``RefreshTokens`` (MUST query on
    every rotation so iOS sees fresh state after the user finishes the
    onboarding flow mid-session).
    """

    user: User | None = None
    onboarding_completed: bool = False
    onboarding_call_count: int = 0
    updated: User | None = None

    async def get_by_id(self, user_id: UUID) -> User | None:
        return self.user

    async def get_by_email(self, email: str) -> User | None:
        return self.user if self.user and self.user.email == email else None

    async def get_by_oauth(self, provider: str, subject: str) -> User | None:
        if (
            self.user
            and self.user.oauth_provider == provider
            and self.user.oauth_subject == subject
        ):
            return self.user
        return None

    async def add(self, user: User) -> None:
        self.user = user

    async def update(self, user: User) -> None:
        self.updated = user

    async def schedule_deletion(self, user_id: UUID, scheduled_for: datetime) -> None: ...
    async def cancel_deletion(self, user_id: UUID) -> None: ...
    async def hard_delete(self, user_id: UUID) -> None: ...

    async def get_onboarding_completed(self, user_id: UUID) -> bool:
        self.onboarding_call_count += 1
        return self.onboarding_completed


@dataclass
class _FakeRefreshRepo:
    added: list[RefreshToken] = field(default_factory=list)
    by_hash: dict[str, RefreshToken] = field(default_factory=dict)

    async def add(self, token: RefreshToken) -> None:
        self.added.append(token)
        self.by_hash[token.token_hash] = token

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        return self.by_hash.get(token_hash)

    async def revoke(self, token_id: UUID, at: datetime) -> None:
        for t in self.added:
            if t.id == token_id:
                t.revoked_at = at

    async def revoke_family(self, family_id: UUID, at: datetime) -> int:
        n = 0
        for t in self.added:
            if t.family_id == family_id and t.revoked_at is None:
                t.revoked_at = at
                n += 1
        return n

    async def mark_reused(self, token_id: UUID, at: datetime) -> None:
        for t in self.added:
            if t.id == token_id:
                t.reused_at = at


@dataclass
class _FakeOtpRepo:
    active: OtpCode | None = None
    consumed: list[UUID] = field(default_factory=list)

    async def add(self, otp: OtpCode) -> None:
        self.active = otp

    async def get_active(self, user_id: UUID, purpose: OtpPurpose) -> OtpCode | None:
        return self.active

    async def increment_attempts(self, otp_id: UUID) -> int:
        return 0

    async def lock(self, otp_id: UUID, until: datetime) -> None: ...

    async def consume(self, otp_id: UUID) -> None:
        self.consumed.append(otp_id)


class _FakeHasher:
    def hash(self, plain: str) -> str:
        return f"argon$:{plain}"

    def verify(self, plain: str, hashed: str) -> bool:
        return hashed == f"argon$:{plain}"


class _FakeJwt:
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


class _FakeOAuthVerifier:
    def __init__(self, payload: dict) -> None:  # type: ignore[type-arg]
        self.payload = payload

    async def verify_id_token(self, id_token: str) -> dict:  # type: ignore[type-arg]
        return self.payload


def _bus() -> EventBus:
    """Real ``EventBus`` with no subscribers — publish is effectively a no-op
    in tests. Cheaper than a fake and avoids Protocol-vs-class type mismatch
    under ``mypy --strict``.
    """
    return EventBus()


def _user(
    *,
    with_password: bool = True,
    oauth: tuple[str, str] | None = None,
    email_verified: bool = True,
) -> User:
    # Default ``email_verified=True`` so Login tests don't have to opt-in:
    # the unverified branch is exercised explicitly by the dedicated test.
    return User(
        id=uuid4(),
        email="miguel@example.com",
        password_hash="argon$:correctsecret" if with_password else None,  # noqa: S106 — test fixture
        oauth_provider=oauth[0] if oauth else None,
        oauth_subject=oauth[1] if oauth else None,
        email_verified=email_verified,
        role="user",
        created_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_user_returns_flag_false_and_skips_profile_lookup() -> None:
    """``RegisterUser`` MUST hardcode ``False`` — the user_profiles row does
    not exist yet, so querying it would be a wasted round trip on a hot path
    (account creation).
    """
    repo = _CountingUserRepo(onboarding_completed=True)  # repo would lie, but...
    uc = RegisterUser(
        users=repo,
        refresh_tokens=_FakeRefreshRepo(),
        hasher=_FakeHasher(),
        jwt=_FakeJwt(),
        bus=_bus(),
    )
    pair = await uc(email="new@example.com", password="correctsecret")  # noqa: S106 — test fixture

    assert pair.onboarding_completed is False
    # The contract: register skips the profile lookup. If this assertion
    # ever flips to ``1``, somebody added a redundant query — review.
    assert repo.onboarding_call_count == 0


@pytest.mark.asyncio
async def test_login_user_returns_flag_true_when_profile_completed() -> None:
    user = _user()
    repo = _CountingUserRepo(user=user, onboarding_completed=True)
    uc = LoginUser(
        users=repo,
        refresh_tokens=_FakeRefreshRepo(),
        hasher=_FakeHasher(),
        jwt=_FakeJwt(),
        bus=_bus(),
    )
    pair = await uc(email=user.email, password="correctsecret")  # noqa: S106 — test fixture

    assert pair.onboarding_completed is True
    assert repo.onboarding_call_count == 1


@pytest.mark.asyncio
async def test_login_user_returns_flag_false_when_profile_missing() -> None:
    """No profile row yet (or row with ``onboarding_completed=False``) → iOS
    must be routed to onboarding."""
    user = _user()
    repo = _CountingUserRepo(user=user, onboarding_completed=False)
    uc = LoginUser(
        users=repo,
        refresh_tokens=_FakeRefreshRepo(),
        hasher=_FakeHasher(),
        jwt=_FakeJwt(),
        bus=_bus(),
    )
    pair = await uc(email=user.email, password="correctsecret")  # noqa: S106 — test fixture

    assert pair.onboarding_completed is False
    assert repo.onboarding_call_count == 1


@pytest.mark.asyncio
async def test_refresh_re_queries_flag_for_freshness_contract() -> None:
    """Refresh MUST re-query on every rotation. Otherwise iOS keeps the
    stale value past 15 min (the access-token TTL window where the user may
    have completed onboarding in another tab/device)."""
    user = _user()
    refresh_repo = _FakeRefreshRepo()
    jwt = _FakeJwt()

    # Seed an active refresh token belonging to the user.
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

    # Flag starts False; will flip True between two rotations.
    repo = _CountingUserRepo(user=user, onboarding_completed=False)
    uc = RefreshTokens(
        users=repo,
        refresh_tokens=refresh_repo,
        jwt=jwt,
        bus=_bus(),
    )

    first = await uc(refresh_plain=plain)
    assert first.onboarding_completed is False
    assert repo.onboarding_call_count == 1

    # Simulate the event-handler flipping the flag mid-session.
    repo.onboarding_completed = True

    # Use the newly issued refresh to rotate again.
    second = await uc(refresh_plain=first.refresh)
    assert second.onboarding_completed is True
    # Each rotation MUST trigger a lookup — total of two now.
    assert repo.onboarding_call_count == 2


@pytest.mark.asyncio
async def test_oauth_login_new_user_returns_flag_false() -> None:
    """First-time OAuth signup — no profile row yet, flag must be False
    regardless of what a stale lookup might return."""
    repo = _CountingUserRepo(user=None, onboarding_completed=False)
    uc = OAuthLogin(
        users=repo,
        refresh_tokens=_FakeRefreshRepo(),
        jwt=_FakeJwt(),
        bus=_bus(),
        verifier=_FakeOAuthVerifier(
            {"sub": "apple-sub-123", "email": "new@apple.com", "email_verified": True}
        ),
        provider="apple",
    )
    pair = await uc(id_token="x" * 32)

    assert pair.onboarding_completed is False
    assert repo.user is not None  # user was created
    assert repo.onboarding_call_count == 1


@pytest.mark.asyncio
async def test_oauth_login_existing_user_returns_repo_value() -> None:
    """Returning OAuth user who finished onboarding previously → flag True."""
    user = _user(with_password=False, oauth=("google", "google-sub-456"))
    user.email = "returning@gmail.com"
    repo = _CountingUserRepo(user=user, onboarding_completed=True)
    uc = OAuthLogin(
        users=repo,
        refresh_tokens=_FakeRefreshRepo(),
        jwt=_FakeJwt(),
        bus=_bus(),
        verifier=_FakeOAuthVerifier(
            {"sub": "google-sub-456", "email": user.email, "email_verified": True}
        ),
        provider="google",
    )
    pair = await uc(id_token="x" * 32)

    assert pair.onboarding_completed is True
    assert repo.onboarding_call_count == 1


@pytest.mark.asyncio
async def test_verify_otp_login_purpose_returns_repo_value() -> None:
    """OTP login (passwordless) for an existing onboarded user → flag True."""
    user = _user(with_password=False)
    repo = _CountingUserRepo(user=user, onboarding_completed=True)
    hasher = _FakeHasher()
    otp_repo = _FakeOtpRepo()
    otp = OtpCode(
        id=uuid4(),
        user_id=user.id,
        code_hash=hasher.hash("123456"),
        purpose="login",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    otp_repo.active = otp

    uc = VerifyOtp(
        users=repo,
        otps=otp_repo,
        refresh_tokens=_FakeRefreshRepo(),
        hasher=hasher,
        jwt=_FakeJwt(),
        bus=_bus(),
    )
    pair = await uc(email=user.email, purpose="login", code="123456")

    assert pair.onboarding_completed is True
    assert repo.onboarding_call_count == 1


@pytest.mark.asyncio
async def test_verify_otp_register_purpose_returns_false_when_no_profile() -> None:
    """OTP-register flow: even after email_verified flip, profile row still
    does not exist → flag False, iOS routes to onboarding."""
    user = _user(with_password=False)
    repo = _CountingUserRepo(user=user, onboarding_completed=False)
    hasher = _FakeHasher()
    otp_repo = _FakeOtpRepo()
    otp = OtpCode(
        id=uuid4(),
        user_id=user.id,
        code_hash=hasher.hash("654321"),
        purpose="register",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    otp_repo.active = otp

    uc = VerifyOtp(
        users=repo,
        otps=otp_repo,
        refresh_tokens=_FakeRefreshRepo(),
        hasher=hasher,
        jwt=_FakeJwt(),
        bus=_bus(),
    )
    pair = await uc(email=user.email, purpose="register", code="654321")

    assert pair.onboarding_completed is False
    assert repo.onboarding_call_count == 1
    # email_verified flip is a side effect we also lock down.
    assert repo.updated is not None
    assert repo.updated.email_verified is True
