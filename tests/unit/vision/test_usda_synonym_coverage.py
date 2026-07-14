"""Unit — USDA grounding coverage: LATAM synonyms, subset match, mismatch guard.

Regression cover for the 2026-07-14 grounding-coverage work. Goal: fewer real
LATAM plate foods fall to the group-average fallback, and NO food resolves to a
spelling-similar-but-wrong entry (arveja→avena, camote→chayote) or to a
condiment/composite the query never asked for (ensalada→"Salad dressing").

All expected values come from the EXISTING verified reference tables — nothing
here asserts an invented number; it asserts the lookup routes to the right
entry.
"""
from __future__ import annotations

import pytest

from app.vision.infrastructure import usda_fdc as u


@pytest.fixture(autouse=True)
def _loaded() -> None:
    u._ensure_loaded()


def _resolve(name: str):
    """Sync slice of the cascade: ingredient_ref → nutrition_reference → SR."""
    r = u._search_ingredient_ref(name) or u._search_nutrition_reference(name)
    if r is None:
        r = u._search_sr_legacy(u._translate(name))
    return r


# ── Subset match: a bare query resolves to a more-specific reference entry ──────
@pytest.mark.parametrize(
    "name",
    ["bistec", "lentejas", "fideos", "chuleta de cerdo"],
)
def test_subset_match_resolves_bare_query(name: str) -> None:
    r = _resolve(name)
    assert r is not None, f"{name} fell to group fallback"
    assert r.kcal_per_100g > 0


# ── Regional synonyms redirect to a canonical entry (no invented values) ───────
@pytest.mark.parametrize(
    ("name", "canonical_hint"),
    [
        ("palta", "avocado"),   # → aguacate
        ("frejol", None),       # → frijoles
        ("poroto", None),       # → frijoles
        ("camote", None),       # → batata
        ("tallarin", None),     # → fideos
    ],
)
def test_synonym_redirects(name: str, canonical_hint: str | None) -> None:
    r = _resolve(name)
    assert r is not None, f"{name} synonym did not resolve"
    if canonical_hint:
        assert canonical_hint in r.description.lower()


# ── Anti-mismatch: spelling-similar wrong foods must NOT win ────────────────────
def test_arveja_is_peas_not_buckwheat() -> None:
    r = _resolve("arveja")
    assert r is not None
    # Green peas ≈ 81 kcal/100g cooked; buckwheat groats ≈ 346 (the old bug).
    assert r.kcal_per_100g < 150, f"arveja resolved to {r.kcal_per_100g} (buckwheat?)"


def test_camote_is_sweet_potato_not_chayote() -> None:
    r = _resolve("camote")
    assert r is not None
    # Sweet potato ≈ 86 kcal/100g; chayote ≈ 19-22 (the old difflib bug).
    assert r.kcal_per_100g > 60, f"camote resolved to {r.kcal_per_100g} (chayote?)"


def test_lentejas_is_cooked_not_raw() -> None:
    r = _resolve("lentejas")
    assert r is not None
    # Cooked lentils ≈ 116-120 kcal/100g; raw/dry ≈ 352 (the raw-table bug).
    assert r.kcal_per_100g < 200, f"lentejas resolved to {r.kcal_per_100g} (raw?)"


# ── SR guard: a bare ingredient must not grab a condiment/composite ────────────
def test_sr_guard_skips_dressing_for_bare_query() -> None:
    """'salad' must not resolve to 'Salad dressing, coleslaw' (404 kcal)."""
    r = u._search_sr_legacy("salad")
    if r is not None:
        assert "dressing" not in r.description.lower()
        assert r.kcal_per_100g < 350


def test_sr_guard_skips_restaurant_composite_for_bare_query() -> None:
    """A bare 'beans' query must not grab a composite restaurant dish."""
    r = u._search_sr_legacy("beans")
    if r is not None:
        # Composite dishes (pupusas etc.) live in 'Restaurant Foods' — skipped.
        assert "pupusa" not in r.description.lower()


# ── Head-noun guard: difflib must not flip the head noun on a shared suffix ─────
def test_headsafe_difflib_keeps_head_noun() -> None:
    """'carne de hamburguesa' shares the suffix 'de hamburguesa' with a bun key,
    so plain char-level difflib would match the bun. The head-noun guard keeps
    'carne' and routes it to a beef entry instead."""
    r = u._search_nutrition_reference("carne de hamburguesa")
    assert r is not None
    # Beef ≈ 200-270 kcal/100g; a hamburger bun ≈ 270-300 but is carbs-heavy.
    # The guard must land on a meat entry (carbs ~0), never the bun (carbs high).
    assert r.carbs_per_100g <= 5, f"grounded to a bun-like entry: {r.description}"
    assert r.protein_per_100g >= 15, "should be a protein/beef entry"


def test_headsafe_difflib_unit() -> None:
    keys = ["pan de hamburguesa", "carne de res", "carne molida de res"]
    # head 'carne' present in 'carne de res' → chosen; 'pan de hamburguesa' rejected.
    assert u._headsafe_difflib("carne de hamburguesa", keys, cutoff=0.3) != "pan de hamburguesa"
