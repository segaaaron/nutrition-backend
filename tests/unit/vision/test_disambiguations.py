"""Unit — G3: disambiguation chips.

Verifies:
- _parse_items reads disambiguations from top-level raw dict and maps
  item_index → DetectedFoodItem.ambiguous_options.
- Entries with invalid index or < 2 options are silently ignored.
- Options are capped at 4 entries.
- VISION_SCHEMA has disambiguations property as optional (not in required).
- _items_to_jsonb / _items_from_jsonb round-trip ambiguous_options.
"""
from __future__ import annotations

from app.vision.infrastructure.openai_vision import VISION_SCHEMA, _parse_items
from app.vision.infrastructure.repositories import (
    _items_from_jsonb,
    _items_to_jsonb,
)

# ---------------------------------------------------------------------------
# Base raw item for tests
# ---------------------------------------------------------------------------

_ITEM_RAW = {
    "name": "pollo al horno",
    "portion_kind": "a_granel",
    "count": 1,
    "size_category": "M",
    "estimated_amount_g": 150,
    "kcal": 250,
    "protein_g": 30,
    "carbs_g": 0,
    "fat_g": 10,
    "confidence": 0.6,  # below 0.7 → ambiguous
    "food_group": "protein",
    "role": "main",
    "prep_method": "baked",
    "bbox": None,
}

_ITEM_RAW_CONFIDENT = {**_ITEM_RAW, "confidence": 0.92, "name": "arroz blanco"}


# ---------------------------------------------------------------------------
# _parse_items — disambiguation mapping
# ---------------------------------------------------------------------------

def test_parse_items_applies_disambiguation_to_correct_item() -> None:
    raw = {
        "is_mixed_dish": False,
        "unit_census": "",
        "items": [_ITEM_RAW, _ITEM_RAW_CONFIDENT],
        "disambiguations": [
            {"item_index": 0, "options": ["pollo al horno", "pavo al horno", "carne de res"]},
        ],
    }
    items = _parse_items(raw)
    assert items[0].ambiguous_options == ["pollo al horno", "pavo al horno", "carne de res"]
    assert items[1].ambiguous_options == []  # not ambiguous


def test_parse_items_no_disambiguations_field() -> None:
    raw = {"is_mixed_dish": False, "unit_census": "", "items": [_ITEM_RAW]}
    items = _parse_items(raw)
    assert items[0].ambiguous_options == []


def test_parse_items_empty_disambiguations() -> None:
    raw = {"is_mixed_dish": False, "unit_census": "", "items": [_ITEM_RAW], "disambiguations": []}
    items = _parse_items(raw)
    assert items[0].ambiguous_options == []


def test_parse_items_invalid_index_ignored() -> None:
    raw = {
        "is_mixed_dish": False,
        "unit_census": "",
        "items": [_ITEM_RAW],
        "disambiguations": [
            {"item_index": 99, "options": ["opt1", "opt2"]},  # out of range
        ],
    }
    items = _parse_items(raw)
    assert items[0].ambiguous_options == []


def test_parse_items_single_option_ignored() -> None:
    raw = {
        "is_mixed_dish": False,
        "unit_census": "",
        "items": [_ITEM_RAW],
        "disambiguations": [
            {"item_index": 0, "options": ["solo una opcion"]},  # < 2 → ignored
        ],
    }
    items = _parse_items(raw)
    assert items[0].ambiguous_options == []


def test_parse_items_options_capped_at_4() -> None:
    raw = {
        "is_mixed_dish": False,
        "unit_census": "",
        "items": [_ITEM_RAW],
        "disambiguations": [
            {"item_index": 0, "options": ["a", "b", "c", "d", "e", "f"]},  # 6 → trimmed to 4
        ],
    }
    items = _parse_items(raw)
    assert len(items[0].ambiguous_options) == 4


# ---------------------------------------------------------------------------
# VISION_SCHEMA — disambiguations is optional (not in required)
# ---------------------------------------------------------------------------

def test_vision_schema_disambiguations_not_in_required() -> None:
    assert "disambiguations" not in VISION_SCHEMA["required"]
    assert "disambiguations" in VISION_SCHEMA["properties"]


def test_vision_schema_disambiguation_item_has_required_fields() -> None:
    schema = VISION_SCHEMA["properties"]["disambiguations"]["items"]
    assert schema["required"] == ["item_index", "options"]


# ---------------------------------------------------------------------------
# Repository round-trip: ambiguous_options survives JSONB serialize/deserialize
# ---------------------------------------------------------------------------

def test_items_to_jsonb_includes_ambiguous_options() -> None:
    raw = {
        "is_mixed_dish": False,
        "unit_census": "",
        "items": [_ITEM_RAW],
        "disambiguations": [
            {"item_index": 0, "options": ["pollo al horno", "pavo", "codorniz"]},
        ],
    }
    items = _parse_items(raw)
    jsonb = _items_to_jsonb(items)
    assert jsonb[0]["ambiguous_options"] == ["pollo al horno", "pavo", "codorniz"]


def test_items_from_jsonb_restores_ambiguous_options() -> None:
    raw = {
        "is_mixed_dish": False,
        "unit_census": "",
        "items": [_ITEM_RAW],
        "disambiguations": [
            {"item_index": 0, "options": ["pollo al horno", "pavo"]},
        ],
    }
    items = _parse_items(raw)
    jsonb = _items_to_jsonb(items)
    restored = _items_from_jsonb(jsonb)
    assert restored[0].ambiguous_options == ["pollo al horno", "pavo"]


def test_items_from_jsonb_missing_field_defaults_empty() -> None:
    # Simulate older JSONB row that lacks ambiguous_options.
    old_row = [
        {
            "name": "arroz blanco",
            "estimated_amount_g": 150.0,
            "kcal": 200,
            "protein_g": 4,
            "carbs_g": 44,
            "fat_g": 0,
            "confidence": 0.9,
            "food_group": "grain",
        }
    ]
    restored = _items_from_jsonb(old_row)
    assert restored[0].ambiguous_options == []
