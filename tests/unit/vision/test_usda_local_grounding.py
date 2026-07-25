"""Unit tests for local USDA JSON grounding helpers in macro_grounder.

Covers: _stem, _key_tokens, _local_usda_lookup, _LOCAL_USDA_INDEX size.
All pure functions — no DB, no network, no async.
"""
from __future__ import annotations

import pytest

from app.vision.infrastructure.macro_grounder import (
    _LOCAL_USDA_INDEX,
    _key_tokens,
    _local_usda_lookup,
    _stem,
)


# ---------------------------------------------------------------------------
# _stem
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("token,expected", [
    # Spanish -es plural
    ("frijoles", "frijol"),
    ("champiñones", "champiñon"),
    ("limones", "limon"),
    # Spanish -s plural
    ("espárragos", "espárrago"),
    ("papas", "papa"),
    ("zanahorias", "zanahoria"),
    # English -s
    ("almonds", "almond"),
    ("berries", "berri"),      # ends "es", len=7>4 → strips "es"
    # Short words — no strip (len guard)
    ("res", "res"),            # len=3, untouched
    ("sal", "sal"),            # len=3, untouched
    ("papa", "papa"),          # len=4, no "es"/"s" suffix rule triggers
    # No suffix to strip
    ("pollo", "pollo"),
    ("salmón", "salmón"),
])
def test_stem(token: str, expected: str) -> None:
    assert _stem(token) == expected


# ---------------------------------------------------------------------------
# _key_tokens
# ---------------------------------------------------------------------------

def test_key_tokens_strips_parens() -> None:
    # "(crudo)" must be excluded — it's in parens
    toks = _key_tokens("Salmón (crudo)")
    assert "crudo" not in toks
    assert "salmon" in toks or "salmón" in toks or any("salm" in t for t in toks)


def test_key_tokens_removes_stopwords() -> None:
    toks = _key_tokens("Pechuga de pollo (cruda)")
    assert "de" not in toks
    assert "cruda" not in toks
    # meaningful tokens present
    assert any(t in toks for t in {"pechuga", "pollo"})


def test_key_tokens_stems_plurals() -> None:
    toks = _key_tokens("Frijoles negros cocidos")
    # "frijoles" → "frijol", "cocidos" in stopwords (as "cocidos" → check)
    # "cocidos" IS in stopwords? Let me check: _STOPWORDS has "cocidos"?
    # Yes: "cocidos" is in _STOPWORDS.
    assert "frijol" in toks or "frijoles" not in toks


# ---------------------------------------------------------------------------
# _LOCAL_USDA_INDEX size
# ---------------------------------------------------------------------------

def test_local_usda_index_loaded() -> None:
    # 73 original + 30 added 2026-07-24 (blended foods, dairy, fruits, nuts, vegs)
    assert len(_LOCAL_USDA_INDEX) >= 103, (
        f"Expected ≥103 entries, got {len(_LOCAL_USDA_INDEX)}"
    )


def test_local_usda_index_all_have_kcal() -> None:
    for name, (_toks, entry) in _LOCAL_USDA_INDEX.items():
        assert entry.get("kcal", 0) > 0, f"{name!r} has zero/missing kcal"


# ---------------------------------------------------------------------------
# _local_usda_lookup — positive matches
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("query,expected_kcal_per_100g", [
    ("filete de salmón al horno", 142.0),
    ("pechuga de pollo asada", 120.0),
    ("arroz blanco", 123.0),
    ("frijol negro", 132.0),
    ("aguacate en rodajas", 160.0),
    ("espárragos cocidos", 20.0),
    ("champiñones salteados", 22.0),
    ("brócoli al vapor", 34.0),
    ("quinoa cocida", 120.0),
    ("avena en hojuelas", 346.0),
    ("trucha arco iris a la plancha", 148.0),
    ("tofu firme salteado", 144.0),
    ("lomo de res asado", 150.0),
    ("batata camote asada", 86.0),
    ("aceite de oliva", 884.0),
    ("yogur griego natural", 54.0),
])
def test_local_usda_lookup_positive(query: str, expected_kcal_per_100g: float) -> None:
    result = _local_usda_lookup(query)
    assert result is not None, f"No match for {query!r}"
    assert result.get("kcal") == expected_kcal_per_100g, (
        f"{query!r}: expected {expected_kcal_per_100g}, got {result.get('kcal')}"
    )


# ---------------------------------------------------------------------------
# _local_usda_lookup — negative (no match expected)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("query", [
    "xyz zork mork",
    "galletas crackers",
    "aceite de cocción invisible",   # "aceite" alone hits 1/2 key tokens → below threshold
    "pizza margherita",
    "couve collard verde",           # not in 73 items
])
def test_local_usda_lookup_negative(query: str) -> None:
    result = _local_usda_lookup(query)
    assert result is None, f"Expected no match for {query!r}, got {result}"


# ---------------------------------------------------------------------------
# _local_usda_lookup — disambiguation (wrong food must NOT match)
# ---------------------------------------------------------------------------

def test_arroz_integral_not_blanco() -> None:
    """'arroz integral' must match Arroz integral, not Arroz blanco."""
    result = _local_usda_lookup("arroz integral cocido")
    assert result is not None
    assert result.get("kcal") == 147.0, (
        f"Expected arroz integral (147 kcal/100g), got {result.get('kcal')}"
    )


def test_cooking_oil_not_matched_by_aceite_coccion() -> None:
    """Inferred cooking-fat names must not hit USDA oil entries."""
    result = _local_usda_lookup("aceite de cocción (absorvido)")
    assert result is None
