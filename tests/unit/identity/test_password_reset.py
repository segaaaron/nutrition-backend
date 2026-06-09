"""Unit tests for the ``ResetPassword`` use case.

Coverage matrix (security-critical):

 1. Happy path — OTP valid, email matches → password updated, OTP claimed,
    every active refresh token revoked.
 2. Wrong OTP code → 401 ``otp_invalid``; password NOT mutated; attempts++.
 3. Expired OTP → ``BusinessRuleViolation("otp_expired")``; no mutation.
 4. Weak password (< 8 chars) → ``BusinessRuleViolation("weak_password")``;
    no DB read of the OTP (early guard) → no mutation.
 5. **Cross-user defence**: OTP issued for userA, request body email = userB
    → 401 ``otp_invalid``; password NOT mutated. CRITICAL.
 6. **OTP user_id IS NULL**: a stray register-style OTP queried with
    purpose=reset → 401 ``otp_invalid``; password NOT mutated. CRITICAL.
 7. Unknown email → silent (use case returns None, router maps to 204).
    No exception, no mutation.
 8. Atomic claim race — first call wins, second call loses → 401.
 9. ``revoke_all_for_user`` is called with the OTP-bound user's id.
10. Rate-limit is enforced at the router layer; the use case itself is
    unaware of rate-limiting. Covered separately at router-level tests
    elsewhere; we assert here that no auth/secret data leaks via the use
    case's logging interface (PII hygiene smoke).
11. Already-consumed OTP (claim returns False) → 401.
12. Audit log emits ``password.reset_completed`` with a user_id_hash and
    NO email plaintext.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.core.errors import BusinessRuleViolation, InvalidCredentials, LockedError
from app.identity.application.use_cases import OTP_MAX_ATTEMPTS, ResetPassword
from app.identity.domain.entities import OtpCode, OtpPurpose, RefreshToken, User


# ---------------------------------------------------------------------------
# Fakes — minimal protocol-shaped doubles.
# ---------------------------------------------------------------------------


@dataclass
class _UserRepo:
    by_id: dict[UUID, User] = field(default_factory=dict)
    updated: list[User] = field(default_factory=list)

    async def get_by_id(self, user_id: UUID) -> User | None:
        return self.by_id.get(user_id)

    async def get_by_email(self, email: str) -> User | None:
        for u in self.by_id.values():
            if u.email == email:
                return u
        return None

    async def get_by_oauth(self, provider: str, subject: str) -> User | None:
        return None

    async def add(self, user: User) -> None:
        self.by_id[user.id] = user

    async def update(self, user: User) -> None:
        self.by_id[user.id] = user
        self.updated.append(user)

    async def schedule_deletion(self, user_id: UUID, scheduled_for: datetime) -> None: ...
    async def cancel_deletion(self, user_id: UUID) -> None: ...
    async def hard_delete(self, user_id: UUID) -> None: ...

    async def get_onboarding_completed(self, user_id: UUID) -> bool:
        return False


@dataclass
class _OtpRepo:
    rows: dict[UUID, OtpCode] = field(default_factory=dict)
    # Toggle so test #11 / #8 can simulate "another caller already claimed".
    claim_returns_false_for: set[UUID] = field(default_factory=set)
    attempts: dict[UUID, int] = field(default_factory=dict)
    locked: dict[UUID, datetime] = field(default_factory=dict)

    async def add(self, otp: OtpCode) -> None:
        self.rows[otp.id] = otp

    async def get_active(self, user_id: UUID, purpose: OtpPurpose) -> OtpCode | None:
        for o in self.rows.values():
            if o.user_id == user_id and o.purpose == purpose:
                return o
        return None

    async def get_active_by_email(
        self, email: str, purpose: OtpPurpose
    ) -> OtpCode | None:
        for o in self.rows.values():
            if o.email == email and o.purpose == purpose:
                return o
        return None

    async def increment_attempts(self, otp_id: UUID) -> int:
        self.attempts[otp_id] = self.attempts.get(otp_id, 0) + 1
        if otp_id in self.rows:
            self.rows[otp_id].attempts = self.attempts[otp_id]
        return self.attempts[otp_id]

    async def lock(self, otp_id: UUID, until: datetime) -> None:
        self.locked[otp_id] = until
        if otp_id in self.rows:
            self.rows[otp_id].locked_until = until

    async def consume(self, otp_id: UUID) -> None:
        self.rows.pop(otp_id, None)

    async def claim(self, otp_id: UUID) -> bool:
        if otp_id in self.claim_returns_false_for:
            return False
        if otp_id not in self.rows:
            return False
        self.rows.pop(otp_id)
        return True


@dataclass
class _RefreshRepo:
    tokens: dict[UUID, RefreshToken] = field(default_factory=dict)
    revoked_for_user: list[tuple[UUID, datetime]] = field(default_factory=list)

    async def add(self, token: RefreshToken) -> None:
        self.tokens[token.id] = token

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        for t in self.tokens.values():
            if t.token_hash == token_hash:
                return t
        return None

    async def revoke(self, token_id: UUID, at: datetime) -> None:
        if token_id in self.tokens:
            self.tokens[token_id].revoked_at = at

    async def revoke_family(self, family_id: UUID, at: datetime) -> int:
        n = 0
        for t in self.tokens.values():
            if t.family_id == family_id and t.revoked_at is None:
                t.revoked_at = at
                n += 1
        return n

    async def mark_reused(self, token_id: UUID, at: datetime) -> None: ...

    async def revoke_all_for_user(self, user_id: UUID, at: datetime) -> int:
        self.revoked_for_user.append((user_id, at))
        n = 0
        for t in self.tokens.values():
            if t.user_id == user_id and t.revoked_at is None:
                t.revoked_at = at
                n += 1
        return n


class _Hasher:
    """Deterministic, reversible-by-string hasher. Sufficient for unit tests."""

    def hash(self, plain: str) -> str:
        return f"argon$:{plain}"

    def verify(self, plain: str, hashed: str) -> bool:
        return hashed == f"argon$:{plain}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _user(email: str = "victim@example.com") -> User:
    return User(
        id=uuid4(),
        email=email,
        password_hash="argon$:oldsecret",  # noqa: S106 — fixture
        oauth_provider=None,
        oauth_subject=None,
        email_verified=True,
        role="user",
        created_at=datetime.now(UTC),
    )


def _otp_for_reset(user: User, *, code: str = "654321", ttl_min: int = 10) -> OtpCode:
    return OtpCode(
        id=uuid4(),
        user_id=user.id,
        email=user.email,
        password_hash=None,
        code_hash=_Hasher().hash(code),
        purpose="reset",
        expires_at=datetime.now(UTC) + timedelta(minutes=ttl_min),
    )


def _build(users, otps, refresh):
    return ResetPassword(
        users=users,
        otps=otps,
        refresh_tokens=refresh,
        hasher=_Hasher(),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reset_password_success() -> None:
    user = _user()
    otp = _otp_for_reset(user, code="654321")
    repo_users = _UserRepo(by_id={user.id: user})
    repo_otps = _OtpRepo(rows={otp.id: otp})
    repo_refresh = _RefreshRepo()
    # Pre-existing active session — must be revoked at the end.
    rt = RefreshToken(
        id=uuid4(),
        user_id=user.id,
        token_hash="hash:active",  # noqa: S106
        family_id=uuid4(),
        parent_id=None,
        expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    await repo_refresh.add(rt)

    uc = _build(repo_users, repo_otps, repo_refresh)
    result = await uc(
        email=user.email, code="654321", new_password="newsecret123"  # noqa: S106
    )

    assert result is None
    assert user.password_hash == "argon$:newsecret123"
    assert otp.id not in repo_otps.rows  # consumed
    assert repo_refresh.revoked_for_user and repo_refresh.revoked_for_user[0][0] == user.id
    assert repo_refresh.tokens[rt.id].revoked_at is not None


@pytest.mark.asyncio
async def test_reset_password_invalid_code() -> None:
    user = _user()
    otp = _otp_for_reset(user, code="654321")
    repo_users = _UserRepo(by_id={user.id: user})
    repo_otps = _OtpRepo(rows={otp.id: otp})
    uc = _build(repo_users, repo_otps, _RefreshRepo())

    with pytest.raises(InvalidCredentials) as exc:
        await uc(email=user.email, code="000000", new_password="newsecret123")  # noqa: S106
    assert exc.value.detail == "otp_invalid"
    assert user.password_hash == "argon$:oldsecret"
    assert repo_otps.attempts[otp.id] == 1
    # OTP NOT consumed on bad code.
    assert otp.id in repo_otps.rows


@pytest.mark.asyncio
async def test_reset_password_expired_code() -> None:
    user = _user()
    otp = _otp_for_reset(user, ttl_min=-1)  # already expired
    repo_users = _UserRepo(by_id={user.id: user})
    repo_otps = _OtpRepo(rows={otp.id: otp})
    uc = _build(repo_users, repo_otps, _RefreshRepo())

    with pytest.raises(BusinessRuleViolation) as exc:
        await uc(email=user.email, code="654321", new_password="newsecret123")  # noqa: S106
    assert exc.value.detail == "otp_expired"
    assert user.password_hash == "argon$:oldsecret"


@pytest.mark.asyncio
async def test_reset_password_weak_password() -> None:
    user = _user()
    otp = _otp_for_reset(user)
    repo_users = _UserRepo(by_id={user.id: user})
    repo_otps = _OtpRepo(rows={otp.id: otp})
    uc = _build(repo_users, repo_otps, _RefreshRepo())

    with pytest.raises(BusinessRuleViolation) as exc:
        await uc(email=user.email, code="654321", new_password="short")  # noqa: S106
    assert exc.value.detail == "weak_password"
    assert user.password_hash == "argon$:oldsecret"
    # Early-guard property — OTP not touched.
    assert otp.id in repo_otps.rows
    assert repo_otps.attempts == {}


@pytest.mark.asyncio
async def test_reset_password_email_mismatch_rejects() -> None:
    """CRITICAL — cross-user attack defence.

    Attacker holds an OTP issued for victim@example.com. They submit the OTP
    with their own email attacker@example.com hoping the backend will look
    up a user by the request body's email and update *that* user's password.
    The use case must:

    - Find the OTP via ``get_active_by_email(request.email, 'reset')`` —
      attacker's email returns None → silent path.

    But the more subtle scenario is when the attacker's email exists in
    the DB AND the OTP also exists under that email but is bound to a
    DIFFERENT user_id (only possible via DB corruption / legacy data /
    stale OTP after email change). We simulate that by mocking the lookup
    to return an OTP whose user_id points to victim but whose .email field
    matches attacker.
    """
    victim = _user("victim@example.com")
    attacker = _user("attacker@example.com")
    # Pathological OTP: email field says attacker, but user_id points at
    # victim. This is the cross-user oracle we must refuse.
    bad_otp = OtpCode(
        id=uuid4(),
        user_id=victim.id,
        email=attacker.email,  # mismatch with the user_id binding
        password_hash=None,
        code_hash=_Hasher().hash("654321"),
        purpose="reset",
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    repo_users = _UserRepo(by_id={victim.id: victim, attacker.id: attacker})
    repo_otps = _OtpRepo(rows={bad_otp.id: bad_otp})
    uc = _build(repo_users, repo_otps, _RefreshRepo())

    with pytest.raises(InvalidCredentials) as exc:
        await uc(
            email=attacker.email, code="654321", new_password="newsecret123"  # noqa: S106
        )
    assert exc.value.detail == "otp_invalid"
    # NEITHER user's password changed.
    assert victim.password_hash == "argon$:oldsecret"
    assert attacker.password_hash == "argon$:oldsecret"
    # OTP NOT claimed.
    assert bad_otp.id in repo_otps.rows


@pytest.mark.asyncio
async def test_reset_password_otp_user_id_null_rejects() -> None:
    """CRITICAL — a stray OTP without user_id (impossible in practice for
    purpose='reset', but defensive coverage).

    If an OTP somehow arrives with user_id IS NULL we must refuse — there
    is no safe user to mutate. We must NOT fall back to looking up the user
    by the request body's email.
    """
    victim = _user("victim@example.com")
    bad_otp = OtpCode(
        id=uuid4(),
        user_id=None,  # the offending field
        email=victim.email,
        password_hash=None,
        code_hash=_Hasher().hash("654321"),
        purpose="reset",
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    repo_users = _UserRepo(by_id={victim.id: victim})
    repo_otps = _OtpRepo(rows={bad_otp.id: bad_otp})
    uc = _build(repo_users, repo_otps, _RefreshRepo())

    with pytest.raises(InvalidCredentials) as exc:
        await uc(
            email=victim.email, code="654321", new_password="newsecret123"  # noqa: S106
        )
    assert exc.value.detail == "otp_invalid"
    assert victim.password_hash == "argon$:oldsecret"
    assert bad_otp.id in repo_otps.rows


@pytest.mark.asyncio
async def test_reset_password_email_nonexistent_returns_silent() -> None:
    """Anti-enumeration: unknown email → no exception, no mutation.

    Router maps this to 204. Use case returns None.
    """
    repo_users = _UserRepo()  # empty
    repo_otps = _OtpRepo()  # empty
    repo_refresh = _RefreshRepo()
    uc = _build(repo_users, repo_otps, repo_refresh)

    result = await uc(
        email="ghost@example.com", code="654321", new_password="newsecret123"  # noqa: S106
    )
    assert result is None
    assert repo_users.updated == []
    assert repo_refresh.revoked_for_user == []


@pytest.mark.asyncio
async def test_reset_password_atomic_concurrent_claim() -> None:
    """Two concurrent reset calls with the same OTP — only the first wins.

    Simulated by marking the OTP as already-claimed before the second call:
    repo.claim() returns False on the second invocation.
    """
    user = _user()
    otp = _otp_for_reset(user, code="654321")
    repo_users = _UserRepo(by_id={user.id: user})
    repo_otps = _OtpRepo(rows={otp.id: otp})
    # Pre-arm: this OTP is already claimed by a concurrent winner.
    repo_otps.claim_returns_false_for.add(otp.id)
    uc = _build(repo_users, repo_otps, _RefreshRepo())

    with pytest.raises(InvalidCredentials) as exc:
        await uc(email=user.email, code="654321", new_password="newsecret123")  # noqa: S106
    assert exc.value.detail == "otp_invalid"
    # Loser of the race did NOT mutate password.
    assert user.password_hash == "argon$:oldsecret"


@pytest.mark.asyncio
async def test_reset_password_revokes_all_refresh_tokens() -> None:
    user = _user()
    otp = _otp_for_reset(user, code="654321")
    repo_users = _UserRepo(by_id={user.id: user})
    repo_otps = _OtpRepo(rows={otp.id: otp})
    repo_refresh = _RefreshRepo()
    # Three live sessions across two devices.
    for _ in range(3):
        await repo_refresh.add(
            RefreshToken(
                id=uuid4(),
                user_id=user.id,
                token_hash=f"hash:{uuid4()}",
                family_id=uuid4(),
                parent_id=None,
                expires_at=datetime.now(UTC) + timedelta(days=30),
            )
        )
    uc = _build(repo_users, repo_otps, repo_refresh)
    await uc(email=user.email, code="654321", new_password="newsecret123")  # noqa: S106

    assert len(repo_refresh.revoked_for_user) == 1
    assert repo_refresh.revoked_for_user[0][0] == user.id
    assert all(t.revoked_at is not None for t in repo_refresh.tokens.values())


@pytest.mark.asyncio
async def test_reset_password_lockout_after_max_attempts() -> None:
    """Brute-force protection mirrors /auth/otp/verify: hitting
    OTP_MAX_ATTEMPTS wrong codes locks the OTP."""
    user = _user()
    otp = _otp_for_reset(user, code="654321")
    repo_users = _UserRepo(by_id={user.id: user})
    repo_otps = _OtpRepo(rows={otp.id: otp})
    uc = _build(repo_users, repo_otps, _RefreshRepo())

    # First (OTP_MAX_ATTEMPTS - 1) wrong submissions raise otp_invalid.
    for _ in range(OTP_MAX_ATTEMPTS - 1):
        with pytest.raises(InvalidCredentials):
            await uc(
                email=user.email, code="000000", new_password="newsecret123"  # noqa: S106
            )

    # The N-th wrong submission triggers the lock.
    with pytest.raises(LockedError):
        await uc(email=user.email, code="000000", new_password="newsecret123")  # noqa: S106

    assert otp.locked_until is not None
    assert user.password_hash == "argon$:oldsecret"


@pytest.mark.asyncio
async def test_reset_password_used_otp_rejected() -> None:
    """Already-consumed OTP (not present in repo) → silent path (router
    maps to 204, identical to unknown email). The previously-consumed
    OTP cannot be replayed because ``get_active_by_email`` returns None.
    """
    user = _user()
    repo_users = _UserRepo(by_id={user.id: user})
    repo_otps = _OtpRepo()  # no active OTP
    repo_refresh = _RefreshRepo()
    uc = _build(repo_users, repo_otps, repo_refresh)

    result = await uc(
        email=user.email, code="654321", new_password="newsecret123"  # noqa: S106
    )
    assert result is None
    assert user.password_hash == "argon$:oldsecret"
    assert repo_refresh.revoked_for_user == []


@pytest.mark.asyncio
async def test_reset_password_audit_log_emits_user_id_hash_no_email(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Audit invariants:

    - On success we emit ``password.reset_completed`` with ``user_id_hash``.
    - We do NOT emit the user's email plaintext in any log record.

    The project uses structlog with a PrintLoggerFactory → stdout, so we
    capture via ``capsys`` rather than the stdlib caplog.
    """
    user = _user("victim@example.com")
    otp = _otp_for_reset(user, code="654321")
    repo_users = _UserRepo(by_id={user.id: user})
    repo_otps = _OtpRepo(rows={otp.id: otp})
    uc = _build(repo_users, repo_otps, _RefreshRepo())

    await uc(email=user.email, code="654321", new_password="newsecret123")  # noqa: S106
    captured = capsys.readouterr()
    full = captured.out + captured.err

    assert "password.reset_completed" in full, f"audit log not emitted: {full!r}"
    assert "user_id_hash" in full
    # PII guard — never log the user's email plaintext.
    assert "victim@example.com" not in full


@pytest.mark.asyncio
async def test_reset_password_user_id_takes_precedence_over_request_email() -> None:
    """Defensive: the user mutated is the one bound to ``OTP.user_id``,
    NEVER a user resolved by re-looking-up the request body's email.

    We construct a scenario where the OTP is bound (correctly) to victim,
    and victim.email == request.email — but a SECOND user (attacker)
    exists in the repo with a DIFFERENT email. The mutation must land on
    victim.id, not on any other row.
    """
    victim = _user("victim@example.com")
    attacker = _user("attacker@example.com")
    otp = _otp_for_reset(victim, code="654321")
    repo_users = _UserRepo(by_id={victim.id: victim, attacker.id: attacker})
    repo_otps = _OtpRepo(rows={otp.id: otp})
    uc = _build(repo_users, repo_otps, _RefreshRepo())

    await uc(email=victim.email, code="654321", new_password="newsecret123")  # noqa: S106

    assert victim.password_hash == "argon$:newsecret123"
    assert attacker.password_hash == "argon$:oldsecret"
