"""Unit + property-based tests for :mod:`app.shared.i18n.locale_resolver`.

Acceptance gates (plan §5 Phase 1):

* mypy strict 0 errors, ruff 0 issues.
* 100% branch coverage on ``locale_resolver.py``.
* Property: ``∀ header. resolve_locale(header, None) ∈ {"es","en"}``.
* Property: ``∀ malformed. parse_accept_language(malformed)`` never raises.
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.shared.i18n.locale_resolver import (
    SUPPORTED_LOCALES,
    parse_accept_language,
    resolve_email_locale,
    resolve_locale,
)

# --- parse_accept_language ---------------------------------------------------


def test_parse_none_returns_empty() -> None:
    assert parse_accept_language(None) == []


def test_parse_empty_string_returns_empty() -> None:
    assert parse_accept_language("") == []


def test_parse_single_tag_default_q() -> None:
    assert parse_accept_language("en") == [("en", 1.0)]


def test_parse_strips_region_subtag() -> None:
    assert parse_accept_language("en-US") == [("en", 1.0)]


def test_parse_is_case_insensitive() -> None:
    assert parse_accept_language("EN-us") == [("en", 1.0)]


def test_parse_orders_by_descending_q() -> None:
    result = parse_accept_language("en;q=0.3, es;q=0.9, fr;q=0.5")
    assert result == [("es", 0.9), ("fr", 0.5), ("en", 0.3)]


def test_parse_preserves_insertion_order_on_q_tie() -> None:
    # Stable sort: same q-value -> earlier in header wins.
    result = parse_accept_language("fr, de, en")
    assert result == [("fr", 1.0), ("de", 1.0), ("en", 1.0)]


def test_parse_drops_q_zero() -> None:
    assert parse_accept_language("en;q=0, es;q=1") == [("es", 1.0)]


def test_parse_clamps_q_above_one() -> None:
    assert parse_accept_language("en;q=5.0") == [("en", 1.0)]


def test_parse_clamps_q_below_zero_treated_as_invalid_float() -> None:
    # Negative literal parses as float -> clamped to 0 -> dropped.
    assert parse_accept_language("en;q=-0.5") == []


def test_parse_malformed_q_defaults_to_one() -> None:
    assert parse_accept_language("en;q=abc") == [("en", 1.0)]


def test_parse_skips_empty_segments() -> None:
    assert parse_accept_language(", en, , es") == [
        ("en", 1.0),
        ("es", 1.0),
    ]


def test_parse_skips_non_alpha_primary() -> None:
    assert parse_accept_language("123, en") == [("en", 1.0)]


def test_parse_tolerates_extra_whitespace() -> None:
    assert parse_accept_language("  en ; q = 0.4 ,  es ") == [
        ("es", 1.0),
        ("en", 0.4),
    ]


def test_parse_ignores_extra_params_after_q() -> None:
    assert parse_accept_language("en;q=0.8;foo=bar") == [("en", 0.8)]


# Property: parser never raises on arbitrary input.
@given(st.text())
@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
def test_parse_never_raises(header: str) -> None:
    result = parse_accept_language(header)
    assert isinstance(result, list)
    for tag, q in result:
        assert isinstance(tag, str)
        assert 0.0 < q <= 1.0


# --- resolve_locale ----------------------------------------------------------


@pytest.mark.parametrize(
    ("header", "profile", "expected"),
    [
        # Header wins.
        ("en", "es", "en"),
        ("en-US", "es", "en"),
        ("es-419,en;q=0.8", None, "es"),
        # Profile fallback when header absent/unsupported.
        (None, "en", "en"),
        ("", "en", "en"),
        ("fr,de", "en", "en"),  # unsupported header -> profile
        # Default fallback when nothing matches (D4 = "es").
        (None, None, "es"),
        ("fr-FR", None, "es"),  # unsupported header, no profile
        ("zzz", "fr", "es"),  # both unsupported
    ],
)
def test_resolve_locale_priority(
    header: str | None,
    profile: str | None,
    expected: str,
) -> None:
    assert resolve_locale(header, profile) == expected


def test_resolve_locale_picks_highest_q_supported() -> None:
    # fr has higher q but unsupported -> skip to es.
    assert resolve_locale("fr;q=1.0, es;q=0.5", None) == "es"


def test_resolve_locale_first_supported_wins_over_later() -> None:
    # en appears first with higher q -> wins.
    assert resolve_locale("en;q=0.9, es;q=0.8", None) == "en"


def test_resolve_locale_profile_case_insensitive() -> None:
    assert resolve_locale(None, "EN") == "en"


# Property: every output is supported.
@given(
    header=st.one_of(st.none(), st.text(max_size=200)),
    profile=st.one_of(st.none(), st.text(max_size=10)),
)
@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
def test_resolve_locale_output_always_supported(
    header: str | None,
    profile: str | None,
) -> None:
    assert resolve_locale(header, profile) in SUPPORTED_LOCALES


# --- resolve_email_locale (D5) ----------------------------------------------


@pytest.mark.parametrize(
    ("profile", "header", "expected"),
    [
        # Profile wins over header for transactional mail.
        ("es", "en", "es"),
        ("en", "es", "en"),
        # No profile -> header.
        (None, "en-US", "en"),
        (None, "es-419,fr", "es"),
        # No profile, unsupported header -> default "es".
        (None, "fr-FR", "es"),
        (None, None, "es"),
        # Profile unsupported -> fall through to header.
        ("fr", "en", "en"),
        # Profile unsupported, header unsupported -> default.
        ("fr", "de", "es"),
    ],
)
def test_resolve_email_locale(
    profile: str | None,
    header: str | None,
    expected: str,
) -> None:
    assert resolve_email_locale(profile, header) == expected


@given(
    profile=st.one_of(st.none(), st.text(max_size=10)),
    header=st.one_of(st.none(), st.text(max_size=200)),
)
@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
def test_resolve_email_locale_output_always_supported(
    profile: str | None,
    header: str | None,
) -> None:
    assert resolve_email_locale(profile, header) in SUPPORTED_LOCALES


# --- SUPPORTED_LOCALES guard -------------------------------------------------


def test_supported_locales_is_exactly_mvp_set() -> None:
    """D2 — MVP locales locked to {es, en}. Widening requires plan update."""
    assert SUPPORTED_LOCALES == frozenset({"es", "en"})
