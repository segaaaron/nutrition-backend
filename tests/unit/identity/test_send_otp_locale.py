"""D5 locale resolution for outbound OTP emails.

Phase 5 acceptance scenarios (per
``docs/handoff/2026-06-05-i18n-runtime-locale-propagation-plan.md``):

1. Signup anon ``Accept-Language: en-US,en`` → email EN
2. Password reset profile.locale=es + header=en → email ES (profile wins)
3. No header + no profile → ES

Plus regression guard:

4. Unsupported header (``pt-BR``) + no profile → ES fallback (D2 lock)

These tests exercise the D5 helper + the ``SendOtp`` use case in tandem,
without spinning up FastAPI. The router wiring (Accept-Language Header
binding + profile.locale SELECT) is integration-tested elsewhere; here we
verify that *given* a resolved ``Locale``, the rendered email matches.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.identity.application.use_cases import SendOtp
from app.identity.domain.entities import OtpCode, OtpPurpose, User
from app.shared.domain.email_sender import EmailSender
from app.shared.i18n import resolve_email_locale

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeUserRepo:
    def __init__(self, user: User | None) -> None:
        self._user = user

    async def get_by_id(self, user_id: UUID) -> User | None: ...
    async def get_by_email(self, email: str) -> User | None:
        if self._user and self._user.email == email:
            return self._user
        return None
    async def get_by_oauth(self, provider: str, subject: str) -> User | None: ...
    async def add(self, user: User) -> None: ...
    async def update(self, user: User) -> None: ...
    async def schedule_deletion(self, user_id: UUID, scheduled_for: datetime) -> None: ...
    async def cancel_deletion(self, user_id: UUID) -> None: ...
    async def hard_delete(self, user_id: UUID) -> None: ...
    async def get_onboarding_completed(self, user_id: UUID) -> bool:
        return False


class _FakeOtpRepo:
    def __init__(self) -> None:
        self.added: list[OtpCode] = []

    async def add(self, otp: OtpCode) -> None:
        self.added.append(otp)

    async def get_active(self, user_id: UUID, purpose: OtpPurpose) -> OtpCode | None:
        return None

    async def get_active_by_email(self, email: str, purpose: OtpPurpose) -> OtpCode | None:
        return None

    async def increment_attempts(self, otp_id: UUID) -> int:
        return 0
    async def lock(self, otp_id: UUID, until: datetime) -> None: ...
    async def consume(self, otp_id: UUID) -> None: ...


class _FakeHasher:
    def hash(self, plain: str) -> str:
        return f"hashed:{plain}"

    def verify(self, plain: str, hashed: str) -> bool:
        return hashed == f"hashed:{plain}"


class _RecordingSender(EmailSender):
    def __init__(self) -> None:
        self.calls: list[dict[str, str | None]] = []

    async def send(
        self,
        *,
        to: str,
        subject: str,
        html: str,
        text: str,
        idempotency_key: str | None = None,
    ) -> None:
        self.calls.append(
            {
                "to": to,
                "subject": subject,
                "html": html,
                "text": text,
                "idempotency_key": idempotency_key,
            }
        )


def _user(email: str = "miguel@example.com") -> User:
    return User(
        id=uuid4(),
        email=email,
        password_hash=None,
        oauth_provider=None,
        oauth_subject=None,
        email_verified=False,
        role="user",
        created_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# D5 helper unit tests
# ---------------------------------------------------------------------------


def test_d5_signup_anon_accept_language_en_us_resolves_en() -> None:
    """Acceptance #1: anon signup with ``Accept-Language: en-US,en`` → EN."""
    assert resolve_email_locale(None, "en-US,en") == "en"


def test_d5_reset_profile_es_header_en_resolves_es_profile_wins() -> None:
    """Acceptance #2: profile.locale=es + Accept-Language: en → ES."""
    assert resolve_email_locale("es", "en") == "es"


def test_d5_no_header_no_profile_resolves_es_default() -> None:
    """Acceptance #3: no header, no profile → ES (D4 default)."""
    assert resolve_email_locale(None, None) == "es"


def test_d5_unsupported_header_pt_br_falls_back_to_es() -> None:
    """D2 lock: PT not in MVP supported set → falls through to default."""
    assert resolve_email_locale(None, "pt-BR,pt;q=0.9") == "es"


def test_d5_quality_value_ranking_picks_highest() -> None:
    """RFC 7231 q-value: ``es;q=0.3, en;q=0.9`` → EN."""
    assert resolve_email_locale(None, "es;q=0.3, en;q=0.9") == "en"


# ---------------------------------------------------------------------------
# SendOtp end-to-end (use-case level): locale flows into rendered email
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_signup_register_locale_en_produces_english_subject() -> None:
    """Acceptance #1 wired through SendOtp."""
    user = _user()
    sender = _RecordingSender()
    uc = SendOtp(
        users=_FakeUserRepo(user),
        otps=_FakeOtpRepo(),
        hasher=_FakeHasher(),
        email_sender=sender,
        locale="en",
    )
    code = await uc(email=user.email, purpose="register")
    assert len(sender.calls) == 1
    call = sender.calls[0]
    assert call["subject"] == "Confirm your NOVA account"
    assert code in str(call["html"])
    assert code in str(call["text"])


@pytest.mark.asyncio
async def test_register_otp_allows_new_user_when_no_existing_account() -> None:
    sender = _RecordingSender()
    repo = _FakeUserRepo(None)
    otp_repo = _FakeOtpRepo()
    hasher = _FakeHasher()
    uc = SendOtp(
        users=repo,
        otps=otp_repo,
        hasher=hasher,
        email_sender=sender,
        locale="en",
    )

    code = await uc(
        email="new@example.com",
        purpose="register",
        password_hash=hasher.hash("correctsecret"),
    )

    assert code is not None
    assert sender.calls[0]["to"] == "new@example.com"
    assert len(otp_repo.added) == 1
    assert otp_repo.added[0].email == "new@example.com"


@pytest.mark.asyncio
async def test_reset_locale_es_produces_spanish_reset_subject() -> None:
    """Acceptance #2 wired through SendOtp (profile.locale=es path)."""
    user = _user()
    sender = _RecordingSender()
    uc = SendOtp(
        users=_FakeUserRepo(user),
        otps=_FakeOtpRepo(),
        hasher=_FakeHasher(),
        email_sender=sender,
        locale="es",
    )
    await uc(email=user.email, purpose="reset")
    assert sender.calls[0]["subject"] == "Restablece tu contrasena NOVA"


@pytest.mark.asyncio
async def test_no_locale_defaults_to_es_signup() -> None:
    """Acceptance #3 wired through SendOtp."""
    user = _user()
    sender = _RecordingSender()
    uc = SendOtp(
        users=_FakeUserRepo(user),
        otps=_FakeOtpRepo(),
        hasher=_FakeHasher(),
        email_sender=sender,
        locale=None,
    )
    await uc(email=user.email, purpose="register")
    assert sender.calls[0]["subject"] == "Confirma tu cuenta NOVA"


@pytest.mark.asyncio
async def test_login_purpose_uses_signup_copy_in_resolved_locale() -> None:
    """``login`` purpose reuses signup template (locked decision 4)."""
    user = _user()
    sender = _RecordingSender()
    uc = SendOtp(
        users=_FakeUserRepo(user),
        otps=_FakeOtpRepo(),
        hasher=_FakeHasher(),
        email_sender=sender,
        locale="en",
    )
    await uc(email=user.email, purpose="login")
    assert sender.calls[0]["subject"] == "Confirm your NOVA account"
