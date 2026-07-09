"""Unit — OpenAIVisionProvider._parse_items robustness."""

from __future__ import annotations

from app.vision.infrastructure.openai_vision import _parse_items


def test_parse_drops_malformed_rows() -> None:
    raw = {
        "items": [
            {
                "name": "avena",
                "estimated_amount_g": 60,
                "kcal": 230,
                "protein_g": 7,
                "carbs_g": 40,
                "fat_g": 4,
                "confidence": 0.91,
            },
            {"name": "x"},  # malformed
        ]
    }
    out = _parse_items(raw)
    assert len(out) == 1
    assert out[0].name == "avena"
    assert out[0].kcal == 230


def test_parse_food_group_valid_and_fallback() -> None:
    raw = {
        "items": [
            {
                "name": "tomate",
                "estimated_amount_g": 40,
                "kcal": 7,
                "protein_g": 0,
                "carbs_g": 2,
                "fat_g": 0,
                "confidence": 0.9,
                "food_group": "vegetable",
            },
            {
                "name": "cosa rara",
                "estimated_amount_g": 50,
                "kcal": 90,
                "protein_g": 1,
                "carbs_g": 10,
                "fat_g": 4,
                "confidence": 0.8,
                "food_group": "hallucinated_group",
            },
            {
                # legacy row without food_group (pre-prompt-bump cache)
                "name": "avena",
                "estimated_amount_g": 60,
                "kcal": 230,
                "protein_g": 7,
                "carbs_g": 40,
                "fat_g": 4,
                "confidence": 0.91,
            },
        ]
    }
    out = _parse_items(raw)
    assert [i.food_group for i in out] == ["vegetable", "other", "other"]


def test_parse_count_multiplies_amounts() -> None:
    """count=2 on a double patty → amounts doubled, count=1 (implicit) unchanged."""
    raw = {
        "items": [
            {
                "name": "carne de hamburguesa",
                "count": 2,
                "estimated_amount_g": 120,  # per-unit
                "kcal": 300,
                "protein_g": 25,
                "carbs_g": 0,
                "fat_g": 20,
                "fiber_g": 0,
                "sugar_g": 0,
                "confidence": 0.92,
                "food_group": "protein",
                "role": "main",
                "prep_method": "grilled",
            },
            {
                "name": "pan de hamburguesa",
                # count absent → defaults to 1
                "estimated_amount_g": 50,
                "kcal": 130,
                "protein_g": 4,
                "carbs_g": 25,
                "fat_g": 2,
                "fiber_g": 1,
                "sugar_g": 3,
                "confidence": 0.88,
                "food_group": "grain",
                "role": "side",
                "prep_method": "baked",
            },
        ]
    }
    out = _parse_items(raw)
    assert len(out) == 2

    patty = out[0]
    assert float(patty.estimated_amount_g) == 240.0  # 120 * 2
    assert patty.protein_g == 50                     # 25 * 2
    assert patty.carbs_g == 0
    assert patty.fat_g == 40                         # 20 * 2
    assert patty.fiber_g == 0                        # 0 * 2
    assert patty.sugar_g == 0                        # 0 * 2
    assert patty.count == 2

    bun = out[1]
    assert float(bun.estimated_amount_g) == 50.0    # unchanged (count=1)
    assert bun.protein_g == 4
    assert bun.fiber_g == 1                         # 1 * 1
    assert bun.sugar_g == 3                         # 3 * 1
    assert bun.count == 1


def test_parse_count_clamps_to_minimum_one() -> None:
    raw = {
        "items": [
            {
                "name": "papa frita",
                "count": 0,  # invalid — must clamp to 1
                "estimated_amount_g": 100,
                "kcal": 300,
                "protein_g": 3,
                "carbs_g": 40,
                "fat_g": 14,
                "confidence": 0.85,
            }
        ]
    }
    out = _parse_items(raw)
    assert float(out[0].estimated_amount_g) == 100.0  # no multiplication


def test_parse_count_scales_kcal_min_max() -> None:
    """kcal_min/kcal_max are multiplied by count before range clamping."""
    raw = {
        "items": [
            {
                "name": "albondigas",
                "count": 3,
                "estimated_amount_g": 40,   # per-unit
                "kcal": 80,                  # per-unit → 240 total
                "kcal_min": 70,              # per-unit → 210 total
                "kcal_max": 95,              # per-unit → 285 total
                "protein_g": 6,
                "carbs_g": 4,
                "fat_g": 4,
                "fiber_g": 0,
                "sugar_g": 0,
                "confidence": 0.88,
                "food_group": "protein",
                "role": "main",
                "prep_method": "stewed",
            }
        ]
    }
    out = _parse_items(raw)
    item = out[0]
    assert float(item.estimated_amount_g) == 120.0  # 40 * 3
    assert item.kcal == 240                           # 80 * 3
    # kcal_min = min(70*3=210, kcal_best=240, kcal_raw=240) = 210
    assert item.kcal_min == 210
    # kcal_max = max(95*3=285, kcal_best=240, kcal_raw=240) = 285
    assert item.kcal_max == 285
    assert item.count == 3


def test_parse_clips_confidence() -> None:
    raw = {
        "items": [
            {
                "name": "x",
                "estimated_amount_g": 10,
                "kcal": 5,
                "protein_g": 0,
                "carbs_g": 1,
                "fat_g": 0,
                "confidence": 3.5,
            }
        ]
    }
    out = _parse_items(raw)
    assert out[0].confidence == 1.0
