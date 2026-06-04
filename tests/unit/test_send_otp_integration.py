"""SendOtp use-case — confirms it dispatches the rendered email when an
EmailSender is wired, and stays backward-compatible (no send) when None.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.identity.application.use_cases import SendOtp
from app.identity.domain.entities import OtpCode, OtpPurpose, User
from app.shared.domain.email_sender import EmailSender


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


class _FakeOtpRepo:
    def __init__(self) -> None:
        self.added: list[OtpCode] = []

    async def add(self, otp: OtpCode) -> None:
        self.added.append(otp)

    async def get_active(self, user_id: UUID, purpose: OtpPurpose) -> OtpCode | None:
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


@pytest.mark.asyncio
async def test_send_otp_dispatches_email_when_sender_wired() -> None:
    user = _user()
    sender = _RecordingSender()
    uc = SendOtp(
        users=_FakeUserRepo(user),
        otps=_FakeOtpRepo(),
        hasher=_FakeHasher(),
        email_sender=sender,
        locale="es",
    )
    code = await uc(email=user.email, purpose="login")
    assert len(code) == 6 and code.isdigit()
    assert len(sender.calls) == 1
    call = sender.calls[0]
    assert call["to"] == "miguel@example.com"
    assert call["subject"]
    assert code in str(call["text"])
    assert code in str(call["html"])
    assert call["idempotency_key"]  # OTP id propagated


@pytest.mark.asyncio
async def test_send_otp_skips_dispatch_when_sender_none() -> None:
    user = _user()
    uc = SendOtp(
        users=_FakeUserRepo(user),
        otps=_FakeOtpRepo(),
        hasher=_FakeHasher(),
    )
    code = await uc(email=user.email, purpose="login")
    assert len(code) == 6
