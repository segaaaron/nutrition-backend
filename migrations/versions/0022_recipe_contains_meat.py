"""Add recipes.contains_meat for pescatarian diet filter.

Revision: 0022_recipe_contains_meat
Author:   nova-backend-architect
Date:     2026-06-26

Adds a boolean flag for land-animal meat presence so Layer1 can serve fish
to pescatarian users (currently they get the same `is_vegetarian IS TRUE`
filter which excludes all fish — stricter than required).

Inline backfill: reads existing recipes and classifies via a local copy of
the classify_contains_meat logic. Operates in batches of 500; each batch
uses offset=0 + WHERE IS NULL so the WHERE clause advances the cursor
naturally as rows get updated (avoids the OFFSET-on-shrinking-set bug).
Nullable; NULL rows are treated as contains_meat = True (fail-safe: exclude
from pescatarian pool until classified).

Import note: the classifier regex is copied inline to make this migration
self-contained. Alembic migrations must not import app code (fragile in CI
and greenfield replay).
"""

from __future__ import annotations

import re
import unicodedata

import sqlalchemy as sa
from alembic import op
from sqlalchemy.sql import text

revision = "0022_recipe_contains_meat"
down_revision = "0021_plan_water_ml"
branch_labels = None
depends_on = None

_BATCH = 500

# ── Inline classifier (copy of diet_classifier.classify_contains_meat) ────────
# Kept here so this migration is self-contained and never imports app code.

def _norm(s: str) -> str:
    s = (s or "").lower()
    s = "".join(
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"\s+", " ", s)

_PLANT_OVERRIDES = re.compile(
    r"\b(leche|crema|yogur|yogurt|queso|mantequilla|manteca|helado|bebida|nata)\s+"
    r"(de\s+)?(almendra|coco|soya|soja|avena|arroz|mani|cacahuate|anacardo|nuez|"
    r"nueces|castana|vegetal|vegano|vegana|girasol|sesamo|ajonjoli|maranon)\w*"
)
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
_MEAT_RE = re.compile(_MEAT)
_FISH_RE = re.compile(_FISH)
_SEAFOOD_RE = re.compile(_SEAFOOD)
_LAND_MEAT_STRICT_RE = re.compile(_MEAT.replace(r"filete|escalope|", ""))


def _classify_contains_meat(text: str) -> bool:
    t = _norm(text)
    t = _PLANT_OVERRIDES.sub(" ", t)
    if _LAND_MEAT_STRICT_RE.search(t) is not None:
        return True
    if _MEAT_RE.search(t) is None:
        return False
    return _FISH_RE.search(t) is None and _SEAFOOD_RE.search(t) is None


# ──────────────────────────────────────────────────────────────────────────────


def upgrade() -> None:
    op.add_column("recipes", sa.Column("contains_meat", sa.Boolean(), nullable=True))

    conn = op.get_bind()
    while True:
        # Always offset=0: WHERE IS NULL shrinks naturally as rows are updated.
        # Using OFFSET on a shrinking result set would skip ~half the rows.
        rows = conn.execute(
            text(
                "SELECT r.id, r.name_en, string_agg(f.name_en, ' ') AS components"
                " FROM recipes r"
                " LEFT JOIN recipe_components rc ON rc.recipe_id = r.id"
                " LEFT JOIN foods f ON f.id = rc.food_id"
                " WHERE r.contains_meat IS NULL"
                " GROUP BY r.id, r.name_en"
                " ORDER BY r.id"
                " LIMIT :batch"
            ),
            {"batch": _BATCH},
        ).fetchall()
        if not rows:
            break
        for recipe_id, name_en, components in rows:
            blob = " ".join(filter(None, [name_en, components]))
            has_meat = _classify_contains_meat(blob)
            conn.execute(
                text("UPDATE recipes SET contains_meat = :v WHERE id = :id"),
                {"v": has_meat, "id": recipe_id},
            )


def downgrade() -> None:
    op.drop_column("recipes", "contains_meat")
