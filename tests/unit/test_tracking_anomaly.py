"""Tracking anomaly guard tests (OWASP API4)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.tracking.domain.anomaly import (
    WeightAnomalyError,
    assert_bodyfat_plausible,
    assert_waist_plausible,
    assert_weight_delta_plausible,
    assert_weight_plausible,
)


@pytest.mark.parametrize("weight", [Decimal("25"), Decimal("75"), Decimal("400")])
def test_plausible_weights_accepted(weight):
    assert_weight_plausible(weight)


@pytest.mark.parametrize(
    "weight,reason",
    [
        (Decimal("24.9"), "below_min"),
        (Decimal("0"), "below_min"),
        (Decimal("400.1"), "above_max"),
        (Decimal("9999"), "above_max"),
    ],
)
def test_implausible_weights_rejected(weight, reason):
    with pytest.raises(WeightAnomalyError, match=reason):
        assert_weight_plausible(weight)


@pytest.mark.parametrize("pct", [None, Decimal("3"), Decimal("25"), Decimal("70")])
def test_plausible_bodyfat_accepted(pct):
    assert_bodyfat_plausible(pct)


@pytest.mark.parametrize("pct", [Decimal("2.9"), Decimal("70.1"), Decimal("100")])
def test_implausible_bodyfat_rejected(pct):
    with pytest.raises(WeightAnomalyError):
        assert_bodyfat_plausible(pct)


@pytest.mark.parametrize("waist", [None, Decimal("40"), Decimal("80"), Decimal("250")])
def test_plausible_waist_accepted(waist):
    assert_waist_plausible(waist)


@pytest.mark.parametrize("waist", [Decimal("39"), Decimal("251")])
def test_implausible_waist_rejected(waist):
    with pytest.raises(WeightAnomalyError):
        assert_waist_plausible(waist)


def test_delta_none_last_passes():
    assert_weight_delta_plausible(Decimal("75"), None, 1)


def test_delta_small_passes():
    assert_weight_delta_plausible(Decimal("75"), Decimal("76"), 1)


def test_delta_impossible_one_day_rejects():
    with pytest.raises(WeightAnomalyError, match="weight_delta_too_large"):
        assert_weight_delta_plausible(Decimal("80"), Decimal("65"), 1)


def test_delta_spread_over_days_acceptable():
    # 15kg over 30 days = 0.5kg/day = OK
    assert_weight_delta_plausible(Decimal("80"), Decimal("65"), 30)


def test_delta_clamps_zero_days_to_one():
    # User logs twice same day with 11kg gap → 11kg/1d > 10kg/d → reject
    with pytest.raises(WeightAnomalyError):
        assert_weight_delta_plausible(Decimal("76"), Decimal("65"), 0)
