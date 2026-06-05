"""Tests for `app.plan.domain.water_view.build_water_view`."""

from __future__ import annotations

import pytest

from app.plan.domain.water_view import build_water_view


def test_schedule_sum_matches_total() -> None:
    view = build_water_view(total_ml=2500)
    assert sum(s.ml for s in view.schedule) == 2500
    assert view.total_ml == 2500


def test_n_glasses_is_ceil_division() -> None:
    # 2500 / 250 = 10 exact
    assert build_water_view(total_ml=2500, glass_ml=250).n_glasses == 10
    # 2501 / 250 → ceil = 11
    assert build_water_view(total_ml=2501, glass_ml=250).n_glasses == 11
    # 1500 / 250 = 6
    assert build_water_view(total_ml=1500, glass_ml=250).n_glasses == 6


def test_message_es_default_includes_litres_and_glasses() -> None:
    view = build_water_view(total_ml=2500, locale="es")
    assert "2.5L" in view.message
    assert "10 vasos" in view.message


def test_message_falls_back_to_es_on_unknown_locale() -> None:
    view = build_water_view(total_ml=2500, locale="zz")
    assert "vasos" in view.message  # ES fallback used


@pytest.mark.parametrize("locale", ["es", "pt", "en", "fr", "de"])
def test_message_renders_in_each_supported_locale(locale: str) -> None:
    view = build_water_view(total_ml=2000, locale=locale)
    assert view.message  # non-empty
    assert "2.0L" in view.message


def test_schedule_has_eight_chronological_slots() -> None:
    view = build_water_view(total_ml=2000)
    assert len(view.schedule) == 8
    times = [s.time for s in view.schedule]
    assert times == sorted(times)


def test_invalid_total_ml_raises() -> None:
    with pytest.raises(ValueError):
        build_water_view(total_ml=0)


def test_invalid_glass_ml_raises() -> None:
    with pytest.raises(ValueError):
        build_water_view(total_ml=2000, glass_ml=0)


def test_litres_uses_banker_rounding_one_decimal() -> None:
    # 1550 ml → 1.55 → ROUND_HALF_EVEN to 1.6 (banker: round to nearest even).
    # Decimal('1.55').quantize('0.1', ROUND_HALF_EVEN) == Decimal('1.6')
    view = build_water_view(total_ml=1550, locale="en")
    assert "1.6L" in view.message
