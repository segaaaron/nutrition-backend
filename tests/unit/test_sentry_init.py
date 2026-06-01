from unittest.mock import patch

from app.core.sentry import init_sentry, scrub_pii


def test_init_skips_when_dsn_empty(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "")
    from app.core.config import get_settings
    get_settings.cache_clear()
    with patch("sentry_sdk.init") as mock_init:
        init_sentry()
        mock_init.assert_not_called()


def test_init_calls_sdk_when_dsn_set(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "https://x@sentry.io/1")
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "staging")
    from app.core.config import get_settings
    get_settings.cache_clear()
    with patch("sentry_sdk.init") as mock_init:
        init_sentry()
        mock_init.assert_called_once()
        kwargs = mock_init.call_args.kwargs
        assert kwargs["dsn"] == "https://x@sentry.io/1"
        assert kwargs["environment"] == "staging"
        assert callable(kwargs["before_send"])


def test_scrub_strips_authorization_header():
    event = {"request": {"headers": {"authorization": "Bearer abc123", "x-other": "ok"}}}
    out = scrub_pii(event, hint={})
    assert out["request"]["headers"]["authorization"] == "[Filtered]"
    assert out["request"]["headers"]["x-other"] == "ok"


def test_scrub_strips_email_from_user():
    event = {"user": {"id": "u-1", "email": "x@y.com", "ip_address": "1.2.3.4"}}
    out = scrub_pii(event, hint={})
    assert "email" not in out["user"]
    assert "ip_address" not in out["user"]
    assert out["user"]["id"] == "u-1"
