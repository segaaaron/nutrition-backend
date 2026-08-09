"""Resolve `recipe_components.free_text_name` to USDA per-100g nutrition.

PERMANENT module (not one-shot). Every recipe batch script and every catalog
audit must go through this resolver so nutrition is always traceable to USDA
FoodData Central and never invented.

Reference sources, in priority order:
  1. ``data/usda/usda_ingredient_reference.json``      — curated, macros + micros
  2. ``data/nutrition_reference/ingredient_extra_usda.json`` — SR Legacy verbatim
  3. ``data/nutrition_reference/ingredient_aliases.json``    — curated alias map

Resolution order for a free-text name:
  1. exact key hit
  2. normalized key hit (case/accent/punctuation folded, culinary noise dropped)
  3. curated alias table (exact, then normalized)
  4. UNRESOLVED — hard fail. Never guessed, never fuzzy-matched.

Rule 4 is the point of this module. A fuzzy matcher once mapped "Limón" to
"Salmón (crudo)" — a 0.73 similarity score and a completely wrong food. Silence
is safer than a plausible wrong number, so unresolved names raise.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Final

_ROOT: Final = Path(__file__).resolve().parent.parent
_REF_PATH: Final = _ROOT / "data" / "usda" / "usda_ingredient_reference.json"
_EXTRA_PATH: Final = _ROOT / "data" / "nutrition_reference" / "ingredient_extra_usda.json"
_ALIAS_PATH: Final = _ROOT / "data" / "nutrition_reference" / "ingredient_aliases.json"
_ADDED_SUGAR_PATH: Final = (
    _ROOT / "data" / "nutrition_reference" / "ingredient_added_sugar.json"
)

# Nutrient fields carried per 100 g. `sat_fat_g`, `sugar_g`, `sodium_mg` and
# `fiber_g` are the catalog's safety columns — the audit gates them.
NUTRIENT_FIELDS: Final[tuple[str, ...]] = (
    "kcal", "protein_g", "fat_g", "carbs_g",
    "fiber_g", "sugar_g", "sat_fat_g", "sodium_mg",
    "potassium_mg", "phosphorus_mg", "calcium_mg", "iron_mg", "folate_ug",
)

# Words that describe cut, shape, freshness or packaging. They do not change
# per-100 g composition, so they are dropped before matching. `crudo`/`cocido`
# are NOT here: raw and cooked differ materially and stay distinct keys.
_NOISE: Final[frozenset[str]] = frozenset({
    "de", "del", "la", "el", "los", "las", "en", "y", "o", "con", "sin", "al", "a",
    "para", "tipo", "fresco", "fresca", "frescos", "frescas", "natural", "naturales",
    "picado", "picada", "picados", "picadas", "fino", "fina", "finos", "finas",
    "grande", "grandes", "pequeno", "pequena", "pequenos", "pequenas", "mediano",
    "mediana", "entero", "entera", "enteros", "enteras", "rallado", "rallada",
    "rebanado", "rebanada", "rebanadas", "rodaja", "rodajas", "cubo", "cubos",
    "tira", "tiras", "trozo", "trozos", "lamina", "laminas", "floretes", "ramitos",
    "delgado", "delgada", "delgadas", "grueso", "gruesa", "gruesas", "pelado",
    "pelada", "limpio", "limpia", "limpios", "limpias", "escurrido", "escurrida",
    "escurridos", "escurridas", "congelado", "congelada", "congelados", "congeladas",
    "maduro", "madura", "opcional", "adicional",
})

_UNITS_RE: Final = re.compile(r"\b\d+\s*(g|gr|ml|cm|kg|pza|pzas|c/u|%)\b")

# Cooking state materially changes per-100 g values (water loss on cooking), so
# these tokens are canonicalised and kept, never dropped. Parenthetical content
# is preserved for the same reason: "Espinaca (cruda)" must not collapse onto
# "Espinaca (cocida)".
_STATE: Final[dict[str, str]] = {
    "crudo": "crudo", "cruda": "crudo", "crudos": "crudo", "crudas": "crudo",
    "cocido": "cocido", "cocida": "cocido", "cocidos": "cocido",
    "cocidas": "cocido", "coc": "cocido",
    "seco": "seco", "seca": "seco", "secos": "seco", "secas": "seco",
    "tostado": "tostado", "tostada": "tostado",
}


def _fold(text: str) -> str:
    """Lowercase, strip accents/punctuation/units. Parenthetical content KEPT."""
    s = unicodedata.normalize("NFKD", text.lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = _UNITS_RE.sub(" ", s)
    s = s.replace("_", " ")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return s


def normalize(name: str, *, keep_state: bool = True) -> str:
    """Canonical match key: folded, noise-stripped, state-canonical, sorted.

    ``keep_state=False`` yields the base key used only as a last-resort fallback
    when the free-text name omits raw/cooked entirely.
    """
    tokens = []
    for tok in _fold(name).split():
        if not tok or tok in _NOISE:
            continue
        if tok in _STATE:
            if keep_state:
                tokens.append(_STATE[tok])
            continue
        tokens.append(tok)
    return " ".join(sorted(tokens))


# When a free-text name carries no cooking state, prefer the raw reference
# entry, then the stateless one, then cooked. Fixed order keeps resolution
# reproducible instead of depending on JSON key order.
_STATE_RANK: Final[dict[str, int]] = {"crudo": 0, "": 1, "cocido": 2, "seco": 3, "tostado": 4}


class UnresolvedIngredientError(KeyError):
    """Raised when a free-text ingredient has no USDA-backed match.

    Never catch this to substitute a default. Add the ingredient to
    ``ingredient_aliases.json`` (if it is an existing food under another name)
    or to ``ingredient_extra_usda.json`` (copying SR Legacy values verbatim).
    """


@dataclass(slots=True, frozen=True)
class Nutrition:
    """Per-100 g nutrient vector. Decimal — macro math must not drift."""

    values: dict[str, Decimal]

    def scaled(self, grams: float | Decimal) -> dict[str, Decimal]:
        factor = Decimal(str(grams)) / Decimal("100")
        return {k: v * factor for k, v in self.values.items()}


@lru_cache(maxsize=1)
def _tables() -> tuple[dict[str, dict], dict[str, str], dict[str, str], dict[str, str]]:
    """(nutrition, exact_norm_index, base_norm_index, alias_map). Cached."""
    ref: dict[str, dict] = {}
    for path in (_REF_PATH, _EXTRA_PATH):
        raw = json.loads(path.read_text(encoding="utf-8"))
        for key, rec in raw.items():
            if key.startswith("_") or not isinstance(rec, dict):
                continue
            ref[key] = rec

    norm_index: dict[str, str] = {}
    base_index: dict[str, str] = {}
    for key in ref:
        norm_index.setdefault(normalize(key), key)
        base = normalize(key, keep_state=False)
        state = next((s for s in _STATE_RANK if s and s in normalize(key).split()), "")
        incumbent = base_index.get(base)
        if incumbent is None:
            base_index[base] = key
        else:
            prev_state = next(
                (s for s in _STATE_RANK if s and s in normalize(incumbent).split()), ""
            )
            if _STATE_RANK[state] < _STATE_RANK[prev_state]:
                base_index[base] = key

    alias_raw = json.loads(_ALIAS_PATH.read_text(encoding="utf-8"))
    alias = {k: v for k, v in alias_raw.items() if not k.startswith("_")}

    unknown = {v for v in alias.values() if v not in ref}
    if unknown:
        raise ValueError(
            f"ingredient_aliases.json points at {len(unknown)} keys absent from the "
            f"USDA reference: {sorted(unknown)[:10]}"
        )
    return ref, norm_index, base_index, alias


def resolve_key(name: str) -> str:
    """Free-text ingredient name -> USDA reference key. Raises if unmatched."""
    ref, norm_index, base_index, alias = _tables()

    if name in ref:
        return name
    if name in alias:
        return alias[name]

    key = normalize(name)
    if key in norm_index:
        return norm_index[key]

    # Aliases are matched on their normalized form too, so a new casing or
    # pluralisation of an already-curated name resolves without a new entry.
    for alias_name, target in alias.items():
        if normalize(alias_name) == key:
            return target

    # Last resort: the name omits raw/cooked. Fall back to the state-ranked
    # base index (raw preferred) rather than failing on "Espinaca" vs
    # "Espinaca (cruda)".
    base = normalize(name, keep_state=False)
    if base in base_index:
        return base_index[base]

    raise UnresolvedIngredientError(name)


def nutrition_per_100g(name: str) -> Nutrition:
    """Per-100 g nutrients for a free-text ingredient name."""
    rec = _tables()[0][resolve_key(name)]
    return Nutrition({f: Decimal(str(rec.get(f, 0) or 0)) for f in NUTRIENT_FIELDS})


@lru_cache(maxsize=1)
def _added_sugar_sources() -> frozenset[str]:
    raw = json.loads(_ADDED_SUGAR_PATH.read_text(encoding="utf-8"))
    return frozenset(raw["sources"])


def is_added_sugar_source(name: str) -> bool:
    """True when this ingredient's sugar counts as ADDED (free) sugar.

    FDA definition: sugars added during processing, plus sugars from syrups and
    honey. Whole fruit, plain-dairy lactose and 100% juice are excluded — their
    sugar is intrinsic and does not carry the same metabolic load.
    """
    return resolve_key(name) in _added_sugar_sources()


def compute_recipe(components: list[tuple[str, float]]) -> dict[str, Decimal]:
    """Sum a recipe's nutrients from ``[(ingredient_name, grams), ...]``.

    ``kcal`` is recomputed by Atwater (4/4/9) rather than summed from the
    reference, so stored kcal and stored macros can never disagree.

    ``added_sugar_g`` is the subset of ``sugar_g`` contributed by added-sugar
    ingredients. `FattyLiverGate` filters on it: its 8 g threshold comes from
    WHO/AASLD free-sugar guidance, which whole-fruit sugar was never meant to
    count against.
    """
    total = {f: Decimal("0") for f in NUTRIENT_FIELDS}
    total["added_sugar_g"] = Decimal("0")
    for name, grams in components:
        scaled = nutrition_per_100g(name).scaled(grams)
        for field, value in scaled.items():
            total[field] += value
        if is_added_sugar_source(name):
            total["added_sugar_g"] += scaled["sugar_g"]
    total["kcal"] = (
        total["protein_g"] * 4 + total["carbs_g"] * 4 + total["fat_g"] * 9
    )
    return total


def unresolved(names: list[str]) -> list[str]:
    """Subset of `names` this resolver cannot map. Use in audits and dry-runs."""
    out = []
    for n in names:
        try:
            resolve_key(n)
        except UnresolvedIngredientError:
            out.append(n)
    return out
