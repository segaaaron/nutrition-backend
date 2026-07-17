"""0032 — clear bogus landlocked exclusions from protein smoothies.

Revision: 0032_unblock_landlocked_smoothies
Author:   nova-backend-architect
Date:     2026-07-17

23 smoothies (`Batido …` / `Licuado …`) carry the FULL 46-country landlocked
blacklist in `excluded_countries` — the same list CLAUDE.md §REGLA PAÍSES SIN
MAR defines for sea fish and shellfish. They contain neither. Their
ingredients are fruit, milk, yogurt, oats, peanut butter and whey powder;
their allergens and tags carry nothing marine.

Effect in PROD: users in Bolivia and Paraguay (and 44 other landlocked
markets) lost the entire smoothie block for no reason. Found while auditing a
BO user's plan on 2026-07-17.

The one-off script that wrote these tags is gone from the repo, so the exact
misfire can't be traced; what is checkable is that the recipes are clean, and
that is what this migration keys on rather than a hardcoded id list.

Guarded on all four marine signals — allergens, tags, ingredient names, and
the presence of an ingredient list at all. Six further smoothies are ALSO
wrongly blocked but have zero `recipe_components` rows; they stay blocked
here on purpose, because unblocking a recipe with no ingredient list just
trades one bug for another. They belong to the 166-recipe
no-ingredients backlog (separate sprint).
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0032_unblock_landlocked_smoothies"
down_revision = "0031_recipes_quarantine"
branch_labels = None
depends_on = None

_MARINE_INGREDIENT = (
    r"(pescado|salmon|salmón|atun|atún|camaron|langostino|gamba|langosta|"
    r"cangrejo|pulpo|calamar|almeja|mejillon|ostra|marisco|bacalao|anchoa|"
    r"sardina|alga|espirulina)"
)


def upgrade() -> None:
    conn = op.get_bind()
    res = conn.execute(
        text(
            """
            UPDATE recipes r SET excluded_countries = '{}'
             WHERE 'BO' = ANY(r.excluded_countries)
               AND lower(coalesce(r.name_translations->>'es', r.name_en)) ~ '^(batido|licuado)'
               AND EXISTS (SELECT 1 FROM recipe_components rc WHERE rc.recipe_id = r.id)
               AND NOT (r.allergens && ARRAY['shellfish','molluscs','fish']::allergen_enum[])
               AND NOT (r.tags && ARRAY['shellfish','molluscs','mariscos','sea_fish','pescado_mar']::text[])
               AND NOT EXISTS (
                     SELECT 1 FROM recipe_components rc
                      WHERE rc.recipe_id = r.id
                        AND lower(coalesce(rc.free_text_name, '')) ~ :marine
                   )
            """
        ),
        {"marine": _MARINE_INGREDIENT},
    )
    print(f"0032: unblocked {res.rowcount} smoothies")  # noqa: T201


def downgrade() -> None:
    # No-op: restoring the blacklist would re-introduce the bug. The rows are
    # in the 2026-07-17 pre-fix backup if they are ever genuinely needed.
    pass
