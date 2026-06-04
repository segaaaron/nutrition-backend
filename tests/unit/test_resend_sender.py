"""ResendEmailSender — covers happy path, auth failure, retry-then-success,
retry-exhaustion, transport error, and PII discipline.

Uses ``httpx.MockTransport`` (no extra dep) so we can assert request shape
and simulate provider responses deterministically.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.notifications.infrastructure.resend_sender import ResendEmailSender
from app.shared.domain.email_sender import EmailDeliveryError


def _client_with(
    handler: Callable[[httpx.Request], httpx.Response],
) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_send_success_200() -> None:
    captured: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["url"] = str(req.url)
        captured["auth"] = req.headers.get("authorization")
        captured["idem"] = req.headers.get("idempotency-key")
        captured["body"] = json.loads(req.content)
        return httpx.Response(200, json={"id": "resend-id-123"})

    sender = ResendEmailSender(
        api_key="re_test_key",
        client=_client_with(handler),
    )
    await sender.send(
        to="user@example.com",
        subject="s",
        html="<p>hi</p>",
        text="hi",
        idempotency_key="job-1",
    )
    assert captured["url"] == "https://api.resend.com/emails"
    assert captured["auth"] == "Bearer re_test_key"
    assert captured["idem"] == "job-1"
    assert captured["body"]["from"] == "no-reply@nova-nutrition.com"
    assert captured["body"]["to"] == ["user@example.com"]


@pytest.mark.asyncio
async def test_send_401_raises_delivery_error_without_leaking_key() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Invalid API key"})

    sender = ResendEmailSender(
        api_key="re_secret_key_should_not_leak",
        client=_client_with(handler),
    )
    with pytest.raises(EmailDeliveryError) as exc_info:
        await sender.send(to="u@example.com", subject="s", html="h", text="t")
    assert "re_secret_key_should_not_leak" not in str(exc_info.value)
    assert "401" in str(exc_info.value)


@pytest.mark.asyncio
async def test_send_429_then_200_retries_and_succeeds() -> None:
    calls = {"n": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 2:
            return httpx.Response(429, json={"message": "rate limited"})
        return httpx.Response(200, json={"id": "ok"})

    sender = ResendEmailSender(
        api_key="k",
        client=_client_with(handler),
    )
    # Patch sleep to keep test fast.
    import app.notifications.infrastructure.resend_sender as mod

    async def _no_sleep(_: float) -> None:
        return None

    mod.asyncio.sleep = _no_sleep  # type: ignore[assignment]
    await sender.send(to="u@example.com", subject="s", html="h", text="t")
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_send_5xx_retries_exhausted_raises() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"message": "down"})

    sender = ResendEmailSender(
        api_key="k",
        client=_client_with(handler),
    )
    import app.notifications.infrastructure.resend_sender as mod

    async def _no_sleep(_: float) -> None:
        return None

    mod.asyncio.sleep = _no_sleep  # type: ignore[assignment]
    with pytest.raises(EmailDeliveryError) as exc_info:
        await sender.send(to="u@example.com", subject="s", html="h", text="t")
    assert "503" in str(exc_info.value)


@pytest.mark.asyncio
async def test_send_transport_error_raises_after_retries() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns fail")

    sender = ResendEmailSender(
        api_key="k",
        client=_client_with(handler),
    )
    import app.notifications.infrastructure.resend_sender as mod

    async def _no_sleep(_: float) -> None:
        return None

    mod.asyncio.sleep = _no_sleep  # type: ignore[assignment]
    with pytest.raises(EmailDeliveryError) as exc_info:
        await sender.send(to="u@example.com", subject="s", html="h", text="t")
    assert "transport" in str(exc_info.value)


@pytest.mark.asyncio
async def test_empty_api_key_rejected_at_construction() -> None:
    with pytest.raises(ValueError):
        ResendEmailSender(api_key="")
