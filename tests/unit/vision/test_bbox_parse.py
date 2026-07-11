"""BE-5 — bbox parsing from the LLM response (_parse_items).

Locks the defensive contract: only a complete, in-range, in-bounds box
survives; anything else degrades to None (never a fabricated position).
"""
from __future__ import annotations

from app.vision.infrastructure.openai_vision import _parse_items


def _raw(bbox: object) -> dict:
    return {
        "items": [
            {
                "name": "carne",
                "count": 1,
                "estimated_amount_g": 100,
                "kcal": 200,
                "kcal_min": 180,
                "kcal_max": 220,
                "protein_g": 20,
                "carbs_g": 0,
                "fat_g": 12,
                "fiber_g": 0,
                "sugar_g": 0,
                "confidence": 0.9,
                "food_group": "protein",
                "role": "main",
                "prep_method": "grilled",
                "bbox": bbox,
            }
        ]
    }


def test_valid_bbox_is_parsed() -> None:
    items = _parse_items(_raw({"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4}))
    assert items[0].bbox == (0.1, 0.2, 0.3, 0.4)


def test_null_bbox_is_none() -> None:
    assert _parse_items(_raw(None))[0].bbox is None


def test_out_of_bounds_bbox_rejected() -> None:
    # x + w = 1.4 > 1 → box escapes the image → None (not clamped/fabricated).
    assert _parse_items(_raw({"x": 0.9, "y": 0.1, "w": 0.5, "h": 0.1}))[0].bbox is None
    # negative / >1 coordinate.
    assert _parse_items(_raw({"x": -0.1, "y": 0.1, "w": 0.2, "h": 0.2}))[0].bbox is None


def test_zero_size_bbox_rejected() -> None:
    assert _parse_items(_raw({"x": 0.1, "y": 0.1, "w": 0.0, "h": 0.2}))[0].bbox is None


def test_malformed_bbox_is_none() -> None:
    for bad in ({"x": 0.1, "y": 0.2, "w": 0.3}, {"x": "a", "y": 0.2, "w": 0.3, "h": 0.4}, []):
        assert _parse_items(_raw(bad))[0].bbox is None
