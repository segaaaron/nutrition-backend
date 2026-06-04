"""NullEmailSender — confirms no-op + structured log emission."""

from __future__ import annotations

import pytest

from app.notifications.infrastructure.null_sender import NullEmailSender


@pytest.mark.asyncio
async def test_null_sender_is_noop(capsys: pytest.CaptureFixture[str]) -> None:
    sender = NullEmailSender()
    await sender.send(
        to="user@example.com",
        subject="hi",
        html="<p>x</p>",
        text="x",
        idempotency_key="abc",
    )
    out = capsys.readouterr().out
    assert "mail.skipped" in out
    assert "mail_disabled" in out


@pytest.mark.asyncio
async def test_null_sender_does_not_leak_recipient(
    capsys: pytest.CaptureFixture[str],
) -> None:
    sender = NullEmailSender()
    await sender.send(
        to="leaky@example.com", subject="s", html="h", text="t"
    )
    out = capsys.readouterr().out
    # Raw address must never appear in logs.
    assert "leaky@example.com" not in out
