"""Integrity guard for the ES->EN ingredient translation map (BE-9).

The map (``data/ingredient_translations_es_en.json``) is the source of truth
for the ``recipe_components.name_en`` backfill (migration 0030). If a value is
blank or a key collides case-insensitively with a different translation, the
backfill would write empty/ambiguous English — this test catches that before
it ships.
"""
from __future__ import annotations

import json
from pathlib import Path

MAP_PATH = Path(__file__).resolve().parents[3] / "data" / "ingredient_translations_es_en.json"


def _load() -> dict[str, str]:
    return json.loads(MAP_PATH.read_text(encoding="utf-8"))["translations"]


def test_map_is_non_empty() -> None:
    assert len(_load()) > 500


def test_all_english_values_non_blank() -> None:
    blanks = [k for k, v in _load().items() if not v or not v.strip()]
    assert not blanks, f"blank EN translations for: {blanks[:20]}"


def test_no_ascii_only_key_left_untranslated() -> None:
    # A common failure mode: an entry that just echoes the Spanish. Flag rows
    # where key == value AND the key contains a Spanish-only marker.
    echoed = [
        k
        for k, v in _load().items()
        if k.strip().lower() == v.strip().lower()
        and any(ch in k.lower() for ch in ("á", "é", "í", "ó", "ú", "ñ"))
    ]
    assert not echoed, f"untranslated (key==value) rows: {echoed[:20]}"


def test_case_insensitive_keys_do_not_conflict() -> None:
    seen: dict[str, str] = {}
    conflicts: list[str] = []
    for k, v in _load().items():
        low = k.strip().lower()
        if low in seen and seen[low] != v:
            conflicts.append(f"{low}: {seen[low]!r} vs {v!r}")
        seen[low] = v
    assert not conflicts, f"case-insensitive key conflicts: {conflicts[:20]}"
