"""Unit tests for the cost-cascade decision logic.

Covers:
- `_should_fallback` boundary semantics (empty, min<floor, avg<threshold).
- `_detect_detail_level` PNG threshold (Pillow synthesizes test images).
- Property-based: any confidence vector in [0,1]^n produces the deterministic
  decision specified in the cascade contract.
"""

from __future__ import annotations

import io
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from app.vision.domain.entities import DetectedFoodItem
from app.vision.infrastructure.openai_vision import (
    MIN_ITEM_CONFIDENCE_FLOOR,
    _detect_detail_level,
    _should_fallback,
)


def _item(conf: float) -> DetectedFoodItem:
    return DetectedFoodItem(
        name="x",
        estimated_amount_g=Decimal("10"),
        kcal=1,
        protein_g=0,
        carbs_g=0,
        fat_g=0,
        confidence=conf,
    )


class TestShouldFallback:
    def test_empty_items_triggers_fallback(self) -> None:
        escalate, reason = _should_fallback([], threshold=0.7)
        assert escalate is True
        assert reason == "empty"

    def test_min_below_floor_triggers_fallback(self) -> None:
        items = [_item(0.95), _item(0.4)]  # min below 0.5
        escalate, reason = _should_fallback(items, threshold=0.7)
        assert escalate is True
        assert reason == "min_below_threshold"

    def test_avg_below_threshold_triggers_fallback(self) -> None:
        items = [_item(0.6), _item(0.65)]  # min ok, avg 0.625 < 0.7
        escalate, reason = _should_fallback(items, threshold=0.7)
        assert escalate is True
        assert reason == "low_confidence"

    def test_high_confidence_no_fallback(self) -> None:
        items = [_item(0.9), _item(0.85)]
        escalate, reason = _should_fallback(items, threshold=0.7)
        assert escalate is False
        assert reason == ""

    def test_exact_threshold_no_fallback(self) -> None:
        # avg exactly == threshold should NOT escalate (strict <).
        items = [_item(0.7), _item(0.7)]
        escalate, _ = _should_fallback(items, threshold=0.7)
        assert escalate is False


class TestDetailDetect:
    def _png(self, w: int, h: int) -> bytes:
        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (w, h), (10, 20, 30)).save(buf, format="PNG")
        return buf.getvalue()

    def test_small_image_picks_low(self) -> None:
        assert _detect_detail_level(self._png(400, 400), threshold_px=500) == "low"

    def test_large_image_picks_high(self) -> None:
        assert _detect_detail_level(self._png(800, 800), threshold_px=500) == "high"

    def test_one_short_side_picks_low(self) -> None:
        # Tall narrow image: width<500, height>500 -> low (W AND H rule).
        assert _detect_detail_level(self._png(300, 900), threshold_px=500) == "low"

    def test_unknown_bytes_defaults_high(self) -> None:
        # Conservative fallback: undecodable bytes -> high (preserve accuracy).
        assert _detect_detail_level(b"not-an-image-just-bytes", threshold_px=500) == "high"


class TestCascadeProperty:
    @settings(max_examples=200, deadline=None)
    @given(
        confidences=st.lists(
            st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
            min_size=1,
            max_size=8,
        ),
        threshold=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    )
    def test_decision_is_deterministic_and_spec_aligned(
        self, confidences: list[float], threshold: float
    ) -> None:
        items = [_item(c) for c in confidences]
        escalate, reason = _should_fallback(items, threshold=threshold)
        # Determinism: same input twice -> same output.
        again_escalate, again_reason = _should_fallback(items, threshold=threshold)
        assert escalate == again_escalate
        assert reason == again_reason

        # Spec re-derivation:
        if not confidences:
            assert escalate is True and reason == "empty"
        elif min(confidences) < MIN_ITEM_CONFIDENCE_FLOOR:
            assert escalate is True and reason == "min_below_threshold"
        elif sum(confidences) / len(confidences) < threshold:
            assert escalate is True and reason == "low_confidence"
        else:
            assert escalate is False and reason == ""
