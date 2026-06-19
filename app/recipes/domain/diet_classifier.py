"""Deterministic vegetarian/vegan classifier from ingredient + name text.

Used by the 0017 migration backfill and ``scripts/backfill_diet_flags.py`` to
populate ``recipes.is_vegetarian`` / ``recipes.is_vegan``, which Layer 1
eligibility reads to honour the user's ``dietary_pattern`` (onboarding promise
"NOVA excluirá los alimentos que no comes").

Safety design (post QA 2026-06-16)
----------------------------------
The guarded failure is serving an animal dish to a vegan, so the animal
lexicons MUST be broad — they list not just the animal (``pollo``) but the
CUTS and PREPARATIONS a dish is usually named by (``pechuga``, ``milanesa``,
``hamburguesa``, ``filete``) and specific cheeses/desserts (``feta``,
``helado``). A recipe with no animal marker defaults to vegetarian/vegan, so an
UNDETECTED animal term is the dangerous case — keep these lists exhaustive.

This is still a heuristic. For a hard guarantee the backfill output is
owner-reviewed and Layer 1 treats unclassified (NULL) recipes as excluded for
vegan/vegetarian users. Classify primarily from the ingredient list (more
reliable than the dish name).
"""

from __future__ import annotations

import re
import unicodedata


def _norm(s: str) -> str:
    s = (s or "").lower()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s)


# Plant phrases stripped BEFORE animal-marker matching so "leche de almendras",
# "queso vegano", "mantequilla de mani", "helado de coco" don't trip the lexicons.
_PLANT_OVERRIDES = re.compile(
    r"\b(leche|crema|yogur|yogurt|queso|mantequilla|manteca|helado|bebida|nata)\s+"
    r"(de\s+)?(almendra|coco|soya|soja|avena|arroz|mani|cacahuate|anacardo|nuez|"
    r"nueces|castana|vegetal|vegano|vegana|girasol|sesamo|ajonjoli|maranon)\w*"
)

# Land animals — species, cuts and preparations.
_MEAT = (
    r"\b(pollo|gallina|pavo|pavito|res\b|carne|vacuno|ternera|ternero|bistec|bife|"
    r"lomo|lomito|cerdo|chancho|puerco|cochinillo|lechon|lechona|cordero|borrego|"
    r"chivo|cabrito|conejo|cuy\b|codorniz|perdiz|faisan|pato\b|ganso|jabali|venado|"
    r"pechuga|muslo|contramuslo|pierna|pernil|costilla|costillar|chuleta|chuleton|"
    r"filete|escalope|milanesa|albondiga|hamburguesa|burger|patty|nugget|fiambre|"
    r"embutido|cecina|charqui|morcilla|chistorra|salchichon|butifarra|pastrami|"
    r"prosciutto|jamon|tocino|tocineta|panceta|chorizo|salchicha|salami|mortadela|"
    r"longaniza|chicharron|higado|rinon|mondongo|menudencia|entrana|vacio|matambre|"
    r"churrasco|picanha|anticucho|parrillada|asado de|carne molida|carne picada|"
    r"chicken|\bbeef\b|pork|lamb|mutton|veal|turkey|bacon|\bham\b|sausage|venison|"
    r"\bduck\b|drumstick|sirloin|ribeye|brisket|\bsteak\b|meatball|\bmince\b|hot ?dog|"
    r"pepperoni|prosciutto)"
)
_FISH = (
    r"\b(pescado|atun|salmon|trucha|bonito|merluza|corvina|tilapia|bacalao|sardina|"
    r"anchoa|anchoveta|pejerrey|lenguado|dorado|mero\b|robalo|lubina|congrio|jurel|"
    r"caballa|reineta|surimi|kani|fish|tuna|\bcod\b|anchovy|mackerel|herring|"
    r"sardine|haddock|tilapia)"
)
_SEAFOOD = (
    r"\b(marisco|camaron|langostino|gamba|pulpo|calamar|chipiron|cangrejo|jaiba|"
    r"centollo|almeja|mejillon|choro|ostra|ostion|vieira|langosta|erizo|macha|loco\b|"
    r"caracol|percebe|berberecho|shrimp|prawn|crab|lobster|squid|octopus|clam|mussel|"
    r"oyster|scallop|krill)"
)
_DAIRY = (
    r"\b(leche|queso|yogur|yogurt|crema|nata|mantequilla|manjar|requeson|ricotta|"
    r"mozzarella|parmesano|cheddar|brie|feta|gouda|manchego|burrata|mascarpone|"
    r"provolone|gruyere|camembert|edam|emmental|gorgonzola|roquefort|paneer|halloumi|"
    r"cuajada|kefir|labneh|helado|gelato|flan|natilla|custard|cheesecake|milk|cheese|"
    r"butter|cream|ghee|casein|whey)"
)
_EGG = r"\b(huevo|huevos|clara de huevo|yema|egg|mayonesa|mayonnaise|merengue|frittata|omelette|omelet|quiche)"
_OTHER_ANIMAL = r"\b(miel\b|honey|gelatina|gelatin|grenetina)"

_NONVEG = re.compile("|".join([_MEAT, _FISH, _SEAFOOD]))
_NONVEGAN_EXTRA = re.compile("|".join([_DAIRY, _EGG, _OTHER_ANIMAL]))


def classify_diet(text: str) -> tuple[bool, bool]:
    """Return ``(is_vegetarian, is_vegan)`` for joined ingredient/name text."""
    t = _norm(text)
    t = _PLANT_OVERRIDES.sub(" ", t)
    is_vegetarian = _NONVEG.search(t) is None
    is_vegan = is_vegetarian and _NONVEGAN_EXTRA.search(t) is None
    return is_vegetarian, is_vegan
