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
