"""Sentry init smoke tests.

Confirms:
- ``init_sentry`` is a no-op when SENTRY_DSN is unset (dev/test default).
- ``_before_send`` redacts PII-sensitive keys before transmission.
"""

from __future__ import annotations

from typing import Any

from app.core.observability import _before_send, init_sentry


def test_init_sentry_noop_without_dsn() -> None:
    # Default Settings() has sentry_dsn="" — init must return False, no raise.
    assert init_sentry("api") is False
    assert init_sentry("worker") is False


def test_before_send_redacts_pii_in_tags() -> None:
    event: dict[str, Any] = {
        "tags": {"email": "user@example.com", "request_id": "abc"},
        "extra": {"weight_kg": 70.0, "bmi": 22.5, "feature_flag": "on"},
    }
    out = _before_send(event, {})
    assert out is not None
    assert out["tags"]["email"] == "[redacted]"
    assert out["tags"]["request_id"] == "abc"
    assert out["extra"]["weight_kg"] == "[redacted]"
    assert out["extra"]["bmi"] == "[redacted]"
    assert out["extra"]["feature_flag"] == "on"


def test_before_send_redacts_nested_pii() -> None:
    event: dict[str, Any] = {
        "contexts": {
            "user_profile": {
                "conditions": ["t2"],
                "locale": "es",
            }
        }
    }
    out = _before_send(event, {})
    assert out is not None
    assert out["contexts"]["user_profile"]["conditions"] == "[redacted]"
    assert out["contexts"]["user_profile"]["locale"] == "es"


def test_before_send_scrubs_breadcrumbs() -> None:
    event: dict[str, Any] = {
        "breadcrumbs": {
            "values": [
                {"category": "auth", "data": {"email": "x@y.z"}, "message": "login"},
            ]
        }
    }
    out = _before_send(event, {})
    assert out is not None
    crumb = out["breadcrumbs"]["values"][0]
    assert crumb["data"]["email"] == "[redacted]"
    assert crumb["message"] == "login"
