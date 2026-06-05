"""Tests for app.plan.domain.water_schedule — 8-slot daily distributor."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.plan.domain.water_schedule import build_water_schedule


def test_eight_slots_in_chronological_order() -> None:
    slots = build_water_schedule(total_ml=2500)
    assert len(slots) == 8
    times = [s.time for s in slots]
    assert times == sorted(times)


def test_exact_sum_2500_ml() -> None:
    slots = build_water_schedule(total_ml=2500)
    assert sum(s.ml for s in slots) == 2500


def test_exact_sum_1500_ml() -> None:
    slots = build_water_schedule(total_ml=1500)
    assert sum(s.ml for s in slots) == 1500


def test_exact_sum_4000_ml() -> None:
    slots = build_water_schedule(total_ml=4000)
    assert sum(s.ml for s in slots) == 4000


def test_wake_slot_is_07_00_and_max_weight() -> None:
    slots = build_water_schedule(total_ml=2500)
    wake = slots[0]
    assert wake.time == "07:00"
    assert wake.label == "Al despertar"
    # Wake has weight 2 (joint-max with media tarde & post-cena).
    for s in slots:
        assert wake.ml >= s.ml


def test_invalid_inputs_raise() -> None:
    with pytest.raises(ValueError, match="total_ml"):
        build_water_schedule(total_ml=0)
    with pytest.raises(ValueError, match="glass_ml"):
        build_water_schedule(total_ml=2000, glass_ml=0)


@settings(max_examples=200)
@given(total=st.integers(min_value=1500, max_value=4000))
def test_property_exact_sum_for_any_total(total: int) -> None:
    slots = build_water_schedule(total_ml=total)
    assert sum(s.ml for s in slots) == total
    assert len(slots) == 8


@settings(max_examples=100)
@given(total=st.integers(min_value=1500, max_value=4000))
def test_property_no_negative_slot(total: int) -> None:
    slots = build_water_schedule(total_ml=total)
    for s in slots:
        assert s.ml >= 0


@settings(max_examples=100)
@given(total=st.integers(min_value=1500, max_value=4000))
def test_property_wake_slot_is_joint_max(total: int) -> None:
    slots = build_water_schedule(total_ml=total)
    wake_ml = slots[0].ml
    for s in slots:
        assert wake_ml >= s.ml
