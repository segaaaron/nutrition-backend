"""Tests for MercadoPago webhook HMAC-SHA256 validation.

MP signature spec:
  Header x-signature: ts=<unix_ts>,v1=<hex_sha256>
  Signed manifest: id:<data_id>;request-id:<x-request-id>;ts:<ts>;
  HMAC-SHA256 with MERCADOPAGO_WEBHOOK_SECRET.
  Replay window: 5 minutes.
"""
from __future__ import annotations

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
    old_ts = str(int(time.time()) - 600)
    data_id = "1"
    rid = "r"
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
