"""Unit — OpenAIVisionProvider._parse_items robustness."""
from __future__ import annotations

from app.vision.infrastructure.openai_vision import _parse_items


def test_parse_drops_malformed_rows() -> None:
    raw = {"items": [
        {"name": "avena", "estimated_amount_g": 60, "kcal": 230, "protein_g": 7,
         "carbs_g": 40, "fat_g": 4, "confidence": 0.91},
        {"name": "x"},  # malformed
    ]}
    out = _parse_items(raw)
    assert len(out) == 1
    assert out[0].name == "avena"
    assert out[0].kcal == 230


def test_parse_clips_confidence() -> None:
    raw = {"items": [{"name": "x", "estimated_amount_g": 10, "kcal": 5,
                      "protein_g": 0, "carbs_g": 1, "fat_g": 0, "confidence": 3.5}]}
    out = _parse_items(raw)
    assert out[0].confidence == 1.0
