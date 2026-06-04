"""Sentry SDK bootstrap with privacy-first event filtering.

Public API
----------
init_sentry(component: Literal["api", "worker"]) -> bool
    Idempotent. Returns True if Sentry was initialised, False otherwise
    (e.g. SENTRY_DSN unset, or sentry-sdk not installed for any reason).

Design notes
------------
- **No-op when SENTRY_DSN is empty.** Local dev / tests pay zero cost.
- **PII strip.** ``send_default_pii=False`` (SDK default since 2.x is False,
  asserted explicitly). On top of that, ``before_send`` scrubs any of the
  PII-sensitive keys we use in tags / extras / breadcrumbs. The keys are
  defined in ``_PII_FIELDS`` — extend with care.
- **Component-aware integrations.** API process gets
  FastApiIntegration + AsyncioIntegration. Arq workers get
  AsyncioIntegration only (Arq has no first-party Sentry integration; we
  capture from inside task wrappers if needed).
- **Sample rates conservative.** ``traces_sample_rate=0.1`` keeps perf
  overhead < 2%. Profiles disabled (0.0) until DSN volume is observed.
"""

from __future__ import annotations

from typing import Any, Literal, cast

from app.core.config import get_settings
from app.core.logging import get_logger

_log = get_logger("app.observability")

# Keys we never want to leak into Sentry events. Match (case-insensitive)
# anywhere they appear in tags/extras/contexts/breadcrumbs/request data.
_PII_FIELDS: frozenset[str] = frozenset(
    {
        "email",
        "password",
        "weight_kg",
        "weight",
        "bmi",
        "conditions",
        "phone",
        "ip",
        "authorization",
        "cookie",
    }
)

_initialised: bool = False


def _scrub_mapping(obj: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *obj* with PII-sensitive values redacted in-place
    (recursively). Mutates the copy, never the input."""
    out: dict[str, Any] = {}
    for k, v in obj.items():
        if isinstance(k, str) and k.lower() in _PII_FIELDS:
            out[k] = "[redacted]"
            continue
        if isinstance(v, dict):
            out[k] = _scrub_mapping(cast(dict[str, Any], v))
        else:
            out[k] = v
    return out


def _before_send(event: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any] | None:
    """Drop PII fields from tags / extras / contexts before transmission."""
    for section in ("tags", "extra", "contexts", "user"):
        section_val = event.get(section)
        if isinstance(section_val, dict):
            event[section] = _scrub_mapping(cast(dict[str, Any], section_val))
    # Also scrub request data / breadcrumb payloads if present.
    req = event.get("request")
    if isinstance(req, dict):
        event["request"] = _scrub_mapping(cast(dict[str, Any], req))
    crumbs = event.get("breadcrumbs")
    if isinstance(crumbs, dict) and isinstance(crumbs.get("values"), list):
        scrubbed: list[dict[str, Any]] = []
        for crumb in cast(list[dict[str, Any]], crumbs["values"]):
            if isinstance(crumb, dict):
                scrubbed.append(_scrub_mapping(crumb))
            else:  # pragma: no cover — defensive
                scrubbed.append(crumb)
        crumbs["values"] = scrubbed
    return event


def init_sentry(component: Literal["api", "worker"]) -> bool:
    """Initialise Sentry SDK. Idempotent; safe to call from app & worker.

    Returns True iff the SDK was actually initialised. Returns False if
    SENTRY_DSN is unset (no-op for dev/test) or if sentry-sdk is missing.
    """
    global _initialised
    if _initialised:
        return True

    settings = get_settings()
    if not settings.sentry_dsn:
        _log.info("sentry.disabled", reason="dsn_unset")
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.asyncio import AsyncioIntegration
    except ImportError:  # pragma: no cover — sentry-sdk is a required dep
        _log.warning("sentry.disabled", reason="sdk_missing")
        return False

    integrations: list[Any] = [AsyncioIntegration()]
    if component == "api":
        try:
            from sentry_sdk.integrations.fastapi import FastApiIntegration
            from sentry_sdk.integrations.starlette import StarletteIntegration

            integrations.extend([FastApiIntegration(), StarletteIntegration()])
        except ImportError:  # pragma: no cover
            pass

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.sentry_environment or settings.env,
        release=settings.app_version,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        profiles_sample_rate=settings.sentry_profiles_sample_rate,
        send_default_pii=False,
        integrations=integrations,
        before_send=_before_send,
    )
    _initialised = True
    _log.info(
        "sentry.initialised",
        component=component,
        environment=settings.sentry_environment or settings.env,
        traces_sample_rate=settings.sentry_traces_sample_rate,
    )
    return True


__all__ = ["init_sentry"]
