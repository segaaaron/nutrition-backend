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
    ("avena en hojuelas", 389.0),
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


# ---------------------------------------------------------------------------
# _local_usda_lookup — new single-token USDA alias entries (Fix 1)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("query,expected_kcal,label", [
    ("bacalao", 82.0, "single-token alias for cod"),
    ("nueces", 654.0, "single-token alias for walnuts (stem: nuec)"),
    ("camote", 86.0, "single-token alias for sweet potato"),
    ("avena", 389.0, "single-token alias for rolled oats (cookies entry removed)"),
])
def test_new_usda_single_token_aliases(query: str, expected_kcal: float, label: str) -> None:
    result = _local_usda_lookup(query)
    assert result is not None, f"No match for {query!r} ({label})"
    assert result.get("kcal") == expected_kcal, (
        f"{query!r} ({label}): expected {expected_kcal}, got {result.get('kcal')}"
    )


def test_avena_cookies_entry_removed() -> None:
    """Cookie entry (430 kcal) must NOT contaminate 'avena' queries any more."""
    result = _local_usda_lookup("avena")
    assert result is not None
    assert result.get("kcal") != 430.0, (
        "Cookie entry (kcal=430) still wins for 'avena' — bad data not removed"
    )


def test_avena_en_hojuelas_returns_real_oats_data() -> None:
    """'avena en hojuelas' must resolve to real rolled-oats data (389 kcal/100g, USDA FDC 1101825).
    Entry was previously mislabeled with buckwheat data (346 kcal) — fixed 2026-07-26.
    """
    result = _local_usda_lookup("avena en hojuelas")
    assert result is not None
    assert result.get("kcal") == 389.0, (
        f"Expected 389.0 (USDA rolled oats) for 'avena en hojuelas', got {result.get('kcal')} "
        "(346.0 = buckwheat mislabel that was removed)"
    )


# ---------------------------------------------------------------------------
# _local_usda_lookup — EN→ES bridge (Fix 2)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("en_query,expected_kcal,label", [
    ("cod", 82.0, "bacalao bridge — lean fish, not generic protein (165 kcal/100g)"),
    ("chicken", 120.0, "chicken → pechuga pollo"),
    ("chicken breast", 120.0, "chicken breast → pechuga pollo"),
    ("beef", 150.0, "beef → lomo res"),
    ("oats", 389.0, "oats → avena (rolled oats, not cookies)"),
    ("oatmeal", 389.0, "oatmeal → avena"),
    ("walnuts", 654.0, "walnuts → nueces"),
    ("sweet potato", 86.0, "sweet potato → camote"),
    ("spinach", 23.0, "spinach → espinacas"),
    ("avocado", 160.0, "avocado → aguacate"),
    ("almonds", 579.0, "almonds → almendras"),
    ("eggs", 143.0, "eggs → huevo entero"),
    ("shrimp", 85.0, "shrimp → camaron"),
    ("potato", 77.0, "potato → papa"),
    ("cranberries", 57.0, "cranberries → arandanos"),
])
def test_en_es_bridge_positive(en_query: str, expected_kcal: float, label: str) -> None:
    """English food names must resolve via EN→ES bridge when Spanish lookup fails."""
    result = _local_usda_lookup(en_query)
    assert result is not None, f"EN→ES bridge failed for {en_query!r} ({label})"
    assert result.get("kcal") == expected_kcal, (
        f"{en_query!r} ({label}): expected {expected_kcal}, got {result.get('kcal')}"
    )


@pytest.mark.parametrize("query", [
    "bacon",
    "hot dog",
    "soda",
    "pizza",
    "french fries",
    "fish",      # removed from bridge — too ambiguous (cod=82 vs salmon=208 kcal)
])
def test_en_es_bridge_negative(query: str) -> None:
    """English names not in the bridge must still return None (no phantom matches)."""
    result = _local_usda_lookup(query)
    assert result is None, f"Expected None for {query!r}, got {result}"


def test_cod_corrected_away_from_generic_protein() -> None:
    """Cod is 82 kcal/100g; generic protein fallback is 165. EN bridge must give 82."""
    result = _local_usda_lookup("cod")
    assert result is not None
    kcal = result.get("kcal")
    assert kcal == 82.0, f"Expected 82.0 (actual cod), got {kcal} (generic protein=165 is wrong)"
