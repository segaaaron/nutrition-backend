"""Locale resolution: RFC 7231 §5.3.5 Accept-Language parser + priority rules.

Pure, framework-free, zero deps. Plan §2 decisions locked:

* D1 — priority: ``Accept-Language`` header > ``profile.locale`` > ``"es"``.
* D2 — MVP locales: ``{"es", "en"}``. Unknown tags fall through silently.
* D4 — anon fallback ``"es"`` (LatAm-first pricing).
* D5 — email/OTP rule: ``profile.locale if profile else accept_language else "es"``.
* D9 — KISS parser ≤30 LoC, robust to malformed input (never raises).

The parser intentionally implements the subset of RFC 7231 we need:

* tag = subtag ("-" subtag)*  — we only inspect the *primary* subtag.
* optional ";q=" weight in ``[0.0, 1.0]`` — malformed => 1.0.
* whitespace tolerated around commas and ``;`` separators.
* case-insensitive.

Anything we can't parse is dropped silently — that is the correct posture for
an HTTP header coming from arbitrary clients (RFC says servers MAY ignore
malformed). Property-based tests guarantee the function never raises.
"""

from __future__ import annotations

from typing import Final, Literal, get_args

Locale = Literal["es", "en"]
"""MVP locales (D2). Extending to PT/FR/DE is post-MVP — do NOT widen here."""

SUPPORTED_LOCALES: Final[frozenset[Locale]] = frozenset(get_args(Locale))
"""Canonical set used by every consumer; mirrors ``Locale`` ``Literal`` args."""

_DEFAULT_LOCALE: Final[Locale] = "es"


def parse_accept_language(header: str | None) -> list[tuple[str, float]]:
    """Parse an ``Accept-Language`` header into ``[(primary_subtag, q)]``.

    Returns entries sorted by descending q-value. Stable for equal weights
    (preserves the client's intent ordering — earlier wins on ties, which is
    what RFC 7231 §5.3.1 recommends).

    Never raises. Unknown / malformed segments are dropped silently.

    Args:
        header: Raw HTTP header value or ``None``.

    Returns:
        List of ``(lowercase primary subtag, q-value)`` tuples sorted by
        descending q. Empty list when input is ``None``, empty, or fully
        malformed.
    """
    if not header:
        return []
    out: list[tuple[int, str, float]] = []
    for idx, raw in enumerate(header.split(",")):
        tag, _, params = raw.strip().partition(";")
        primary = tag.strip().split("-", 1)[0].lower()
        if not primary or not primary.isalpha():
            continue
        q = 1.0
        if params:
            for param in params.split(";"):
                k, _, v = param.strip().partition("=")
                if k.strip().lower() == "q":
                    try:
                        q = max(0.0, min(1.0, float(v.strip())))
                    except ValueError:
                        q = 1.0
        if q == 0.0:  # explicit reject per RFC
            continue
        out.append((idx, primary, q))
    # Sort by descending q, ascending insertion idx (stable on equal q).
    out.sort(key=lambda t: (-t[2], t[0]))
    return [(primary, q) for _, primary, q in out]


def _coerce_supported(tag: str | None) -> Locale | None:
    """Return ``tag`` lowercased iff it matches a supported MVP locale."""
    if tag is None:
        return None
    candidate = tag.strip().lower()
    for supported in SUPPORTED_LOCALES:
        if candidate == supported:
            return supported
    return None


def resolve_locale(
    header: str | None,
    profile_locale: str | None,
) -> Locale:
    """Resolve the effective locale for a request (D1 + D4).

    Priority order:

    1. First supported tag in ``Accept-Language``.
    2. ``profile_locale`` if it matches a supported locale.
    3. ``"es"`` (LatAm-first MVP default, D4).

    Args:
        header: Raw ``Accept-Language`` header (may be ``None``).
        profile_locale: Persisted user profile locale (may be ``None``).

    Returns:
        One of :data:`SUPPORTED_LOCALES`.
    """
    for primary, _q in parse_accept_language(header):
        coerced = _coerce_supported(primary)
        if coerced is not None:
            return coerced
    coerced_profile = _coerce_supported(profile_locale)
    if coerced_profile is not None:
        return coerced_profile
    return _DEFAULT_LOCALE


def resolve_email_locale(
    profile_locale: str | None,
    accept_language: str | None,
) -> Locale:
    """Resolve the locale for outbound emails / OTP (D5).

    Rule: ``profile.locale if profile_locale else accept_language else "es"``.
    Profile wins over header for transactional mail so that an existing
    user's preference is not overridden by a borrowed device's headers.

    Args:
        profile_locale: Stored profile locale (``None`` for anon signups).
        accept_language: Raw ``Accept-Language`` header from the request.

    Returns:
        One of :data:`SUPPORTED_LOCALES`.
    """
    coerced_profile = _coerce_supported(profile_locale)
    if coerced_profile is not None:
        return coerced_profile
    for primary, _q in parse_accept_language(accept_language):
        coerced = _coerce_supported(primary)
        if coerced is not None:
            return coerced
    return _DEFAULT_LOCALE
