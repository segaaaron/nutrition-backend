"""Unit tests for vision domain value objects.

Confidence is a 0..1 ratio with explicit boundary enforcement.
VisionPrompt carries the prompt body + its sha256 for audit/versioning.

Two-pass pipeline value objects (added 2026-07-25):
- FoodIdentification  (Call-1 output)
- PortionEstimate     (Call-2 output)
- PortionHint         (catalog-derived prior for Call-2)
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.vision.domain.value_objects import (
    Confidence,
    FoodIdentification,
    PortionEstimate,
    PortionHint,
    VisionPrompt,
)


def test_confidence_accepts_zero():
    assert Confidence(value=0.0).value == 0.0


def test_confidence_accepts_one():
    assert Confidence(value=1.0).value == 1.0


def test_confidence_rejects_just_below_zero():
    with pytest.raises(ValueError, match="confidence_out_of_range"):
        Confidence(value=-0.0001)


def test_confidence_rejects_just_above_one():
    with pytest.raises(ValueError, match="confidence_out_of_range"):
        Confidence(value=1.0001)


@given(v=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
def test_confidence_accepts_any_value_in_unit_interval(v: float) -> None:
    assert Confidence(value=v).value == v


@given(v=st.floats(min_value=1.0001, max_value=1e6, allow_nan=False, allow_infinity=False))
def test_confidence_rejects_above_unit_interval(v: float) -> None:
    with pytest.raises(ValueError):
        Confidence(value=v)


def test_confidence_is_frozen():
    c = Confidence(value=0.5)
    with pytest.raises((AttributeError, Exception)):
        c.value = 0.6  # type: ignore[misc]


def test_vision_prompt_defaults():
    p = VisionPrompt(body="hello", sha256="abc123")
    assert p.locale == "en"
    assert p.region == "us"


def test_vision_prompt_with_locale_region():
    p = VisionPrompt(body="hola", sha256="xyz", locale="es", region="latam")
    assert p.locale == "es"
    assert p.region == "latam"


def test_vision_prompt_is_frozen():
    p = VisionPrompt(body="b", sha256="s")
    with pytest.raises((AttributeError, Exception)):
        p.body = "other"  # type: ignore[misc]


def test_vision_prompt_equality_by_value():
    a = VisionPrompt(body="x", sha256="y")
    b = VisionPrompt(body="x", sha256="y")
    assert a == b


# ---------------------------------------------------------------------------
# FoodIdentification
# ---------------------------------------------------------------------------

def _make_food_id(**kwargs: object) -> FoodIdentification:
    defaults: dict[str, object] = dict(name="arroz", confidence=0.9, group="grain")
    defaults.update(kwargs)
    return FoodIdentification(**defaults)  # type: ignore[arg-type]


def test_food_identification_defaults():
    fi = _make_food_id()
    assert fi.count == 1
    assert fi.portion_kind == "a_granel"
    assert fi.role is None
    assert fi.prep_method is None
    assert fi.bbox is None
    assert fi.inferred is False


def test_food_identification_confidence_boundary_zero():
    fi = _make_food_id(confidence=0.0)
    assert fi.confidence == 0.0


def test_food_identification_confidence_boundary_one():
    fi = _make_food_id(confidence=1.0)
    assert fi.confidence == 1.0


def test_food_identification_confidence_below_zero_raises():
    with pytest.raises(ValueError, match="confidence"):
        _make_food_id(confidence=-0.001)


def test_food_identification_confidence_above_one_raises():
    with pytest.raises(ValueError, match="confidence"):
        _make_food_id(confidence=1.001)


def test_food_identification_count_zero_raises():
    with pytest.raises(ValueError, match="count"):
        _make_food_id(count=0)


def test_food_identification_count_negative_raises():
    with pytest.raises(ValueError, match="count"):
        _make_food_id(count=-1)


def test_food_identification_is_frozen():
    fi = _make_food_id()
    with pytest.raises((AttributeError, TypeError)):
        fi.name = "pollo"  # type: ignore[misc]


def test_food_identification_has_slots():
    fi = _make_food_id()
    assert not hasattr(fi, "__dict__"), "slots=True must remove __dict__"


def test_food_identification_equality_by_value():
    a = _make_food_id(name="pollo", confidence=0.8, group="protein")
    b = _make_food_id(name="pollo", confidence=0.8, group="protein")
    assert a == b


def test_food_identification_pieza_entera_kind():
    fi = _make_food_id(portion_kind="pieza_entera", count=2)
    assert fi.portion_kind == "pieza_entera"
    assert fi.count == 2


def test_food_identification_with_bbox():
    fi = _make_food_id(bbox=(0.1, 0.2, 0.3, 0.4))
    assert fi.bbox == (0.1, 0.2, 0.3, 0.4)


def test_food_identification_inferred_flag():
    fi = _make_food_id(inferred=True)
    assert fi.inferred is True


@given(
    conf=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    count=st.integers(min_value=1, max_value=20),
)
def test_food_identification_property_based_valid(conf: float, count: int) -> None:
    fi = _make_food_id(confidence=conf, count=count)
    assert fi.confidence == conf
    assert fi.count == count


# ---------------------------------------------------------------------------
# PortionEstimate
# ---------------------------------------------------------------------------

def _make_portion_est(**kwargs: object) -> PortionEstimate:
    defaults: dict[str, object] = dict(
        index=0,
        estimated_amount_g=Decimal("150"),
        kcal=200,
        protein_g=5,
        carbs_g=40,
        fat_g=2,
        confidence=0.85,
    )
    defaults.update(kwargs)
    return PortionEstimate(**defaults)  # type: ignore[arg-type]


def test_portion_estimate_valid():
    pe = _make_portion_est()
    assert pe.index == 0
    assert pe.estimated_amount_g == Decimal("150")
    assert pe.kcal == 200


def test_portion_estimate_index_zero_ok():
    pe = _make_portion_est(index=0)
    assert pe.index == 0


def test_portion_estimate_index_negative_raises():
    with pytest.raises(ValueError, match="index"):
        _make_portion_est(index=-1)


def test_portion_estimate_confidence_boundary_zero():
    pe = _make_portion_est(confidence=0.0)
    assert pe.confidence == 0.0


def test_portion_estimate_confidence_boundary_one():
    pe = _make_portion_est(confidence=1.0)
    assert pe.confidence == 1.0


def test_portion_estimate_confidence_above_one_raises():
    with pytest.raises(ValueError, match="confidence"):
        _make_portion_est(confidence=1.0001)


def test_portion_estimate_confidence_below_zero_raises():
    with pytest.raises(ValueError, match="confidence"):
        _make_portion_est(confidence=-0.001)


def test_portion_estimate_is_frozen():
    pe = _make_portion_est()
    with pytest.raises((AttributeError, TypeError)):
        pe.kcal = 999  # type: ignore[misc]


def test_portion_estimate_has_slots():
    pe = _make_portion_est()
    assert not hasattr(pe, "__dict__"), "slots=True must remove __dict__"


def test_portion_estimate_equality_by_value():
    a = _make_portion_est(index=1, kcal=300)
    b = _make_portion_est(index=1, kcal=300)
    assert a == b


def test_portion_estimate_uses_decimal_for_grams():
    pe = _make_portion_est(estimated_amount_g=Decimal("123.456"))
    assert isinstance(pe.estimated_amount_g, Decimal)
    assert pe.estimated_amount_g == Decimal("123.456")


@given(
    idx=st.integers(min_value=0, max_value=50),
    conf=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
)
def test_portion_estimate_property_based_valid(idx: int, conf: float) -> None:
    pe = _make_portion_est(index=idx, confidence=conf)
    assert pe.index == idx
    assert pe.confidence == conf


# ---------------------------------------------------------------------------
# PortionHint
# ---------------------------------------------------------------------------

def test_portion_hint_full():
    ph = PortionHint(name_norm="arroz_blanco", typical_serving_g=150.0, kcal_per_100g=130.0)
    assert ph.name_norm == "arroz_blanco"
    assert ph.typical_serving_g == 150.0
    assert ph.kcal_per_100g == 130.0


def test_portion_hint_none_fields():
    ph = PortionHint(name_norm="desconocido", typical_serving_g=None, kcal_per_100g=None)
    assert ph.typical_serving_g is None
    assert ph.kcal_per_100g is None


def test_portion_hint_is_frozen():
    ph = PortionHint(name_norm="x", typical_serving_g=100.0, kcal_per_100g=80.0)
    with pytest.raises((AttributeError, TypeError)):
        ph.name_norm = "y"  # type: ignore[misc]


def test_portion_hint_has_slots():
    ph = PortionHint(name_norm="x", typical_serving_g=None, kcal_per_100g=None)
    assert not hasattr(ph, "__dict__"), "slots=True must remove __dict__"


def test_portion_hint_equality_by_value():
    a = PortionHint(name_norm="pollo", typical_serving_g=120.0, kcal_per_100g=165.0)
    b = PortionHint(name_norm="pollo", typical_serving_g=120.0, kcal_per_100g=165.0)
    assert a == b
