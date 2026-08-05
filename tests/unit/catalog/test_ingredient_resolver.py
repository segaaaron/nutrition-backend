"""Lock the ingredient resolver's safety properties.

The resolver replaced a fuzzy string matcher that mapped "Limón" to
"Salmón (crudo)" at a 0.73 similarity score — a citrus resolving to a fish,
which would have written salmon's fat and protein into a lemon-garnished
recipe. These tests fence the three properties that keep that from recurring:
an unknown name raises instead of guessing, cooking state is never collapsed,
and every alias points at a real reference entry.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from scripts.ingredient_resolver import (
    NUTRIENT_FIELDS,
    UnresolvedIngredientError,
    compute_recipe,
    normalize,
    nutrition_per_100g,
    resolve_key,
    unresolved,
)

_ROOT = Path(__file__).resolve().parents[3]
_ALIAS_PATH = _ROOT / "data" / "nutrition_reference" / "ingredient_aliases.json"


def test_unknown_ingredient_raises_rather_than_guessing() -> None:
    """The whole point: no silent fallback, no nearest neighbour."""
    with pytest.raises(UnresolvedIngredientError):
        resolve_key("zzz not a food at all zzz")


def test_lemon_never_resolves_to_salmon() -> None:
    """The exact historical mis-match that motivated the rewrite."""
    assert resolve_key("Limón") != "Salmón (crudo)"
    assert "lim" in resolve_key("Limón").lower()


def test_cooking_state_is_not_collapsed() -> None:
    """Raw and cooked differ materially (water loss), so they stay distinct."""
    assert normalize("Espinaca (cruda)") == normalize("Espinaca Cruda")
    assert normalize("Brócoli (cocido)") != normalize("Brócoli (crudo)")


def test_preparation_words_do_not_change_the_match() -> None:
    """Cut and shape do not change per-100 g composition."""
    base = resolve_key("Zanahoria (cruda)")
    for variant in ("Zanahoria en cubos", "Zanahoria rallada",
                    "Zanahoria en rodajas gruesas", "Zanahorias"):
        assert resolve_key(variant) == base


def test_every_alias_targets_a_real_reference_entry() -> None:
    """A dangling alias would resolve to nothing and silently contribute 0."""
    aliases = {k: v for k, v in json.loads(_ALIAS_PATH.read_text("utf-8")).items()
               if not k.startswith("_")}
    assert aliases, "alias table is empty"
    for source, target in aliases.items():
        # The target must be a real reference entry. The source may ALSO be one
        # (e.g. "Pepinillos encurtidos" exists in both), in which case the exact
        # hit wins over the alias — still a valid resolution, so only the
        # target's existence is asserted.
        assert resolve_key(target) == target, f"{source} -> {target}"
        resolve_key(source)  # must not raise


def test_salt_carries_its_sodium() -> None:
    """Salt at 2 g is ~775 mg sodium — a third of the DGA daily cap. Treating
    it as a zero-nutrient condiment was how sodium went missing."""
    sodium = nutrition_per_100g("Sal").values["sodium_mg"]
    assert sodium > Decimal("30000")


def test_compute_recipe_derives_kcal_by_atwater() -> None:
    """Stored kcal must be a function of the macros, never an independent
    number that can drift away from them."""
    total = compute_recipe([("Pechuga de pollo (cruda)", 200.0),
                            ("Arroz blanco cocido", 150.0),
                            ("Aceite de oliva", 10.0)])
    expected = total["protein_g"] * 4 + total["carbs_g"] * 4 + total["fat_g"] * 9
    assert total["kcal"] == expected
    assert total["kcal"] > 0


def test_compute_recipe_scales_linearly_with_grams() -> None:
    single = compute_recipe([("Pechuga de pollo (cruda)", 100.0)])
    double = compute_recipe([("Pechuga de pollo (cruda)", 200.0)])
    for field in NUTRIENT_FIELDS:
        assert double[field] == single[field] * 2, field


def test_unresolved_reports_only_the_bad_names() -> None:
    names = ["Pechuga de pollo (cruda)", "definitely not a food", "Aceite de oliva"]
    assert unresolved(names) == ["definitely not a food"]
