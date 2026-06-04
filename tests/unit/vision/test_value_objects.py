"""Unit tests for vision domain value objects.

Confidence is a 0..1 ratio with explicit boundary enforcement.
VisionPrompt carries the prompt body + its sha256 for audit/versioning.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.vision.domain.value_objects import Confidence, VisionPrompt


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
