"""0034 — generic LATAM recipe names (CLAUDE.md §REGLA DE ORO — Nombres).

Revision: 0034_generic_latam_recipe_names
Author:   nova-backend-architect
Date:     2026-07-17

Eleven `name_translations->>'es'` values break the naming rule: a name must be
understandable to anyone in LATAM, with no foreign culinary terms and no
literal calques from the English name. Found while auditing a BO user's plan
on 2026-07-17, where the plan itself served two of them.

Each replacement follows a pattern the catalog ALREADY uses elsewhere, so
this aligns the outliers rather than inventing vocabulary:

  hummus -> crema de garbanzo
      Arabic term. The catalog already renders it this way in "Enrollado
      integral de pavo con crema de garbanzo y vegetales frescos".

  edamame -> frijoles de soya
      Japanese term. This exact mapping is spelled out in CLAUDE.md's
      prohibited-terms table.

  "Enrollado de desayuno" -> "Enrollado de …"
      Calque of "Breakfast Wrap". The catalog already has "Enrollado de huevo
      y espinacas con queso" without it.

  "Sartén de Desayuno con queso de soya" -> "Tofu salteado con …"
      Calque of "Breakfast Skillet", plus "queso de soya" for tofu — while
      the ingredient map itself uses "Tofu firme".

Owner-approved 2026-07-17. `name_en` is deliberately untouched: it is the
canonical id (ADR-0007) and may stay technical. Keyed on `name_en`, verified
unique across the catalog for all eleven.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0034_generic_latam_recipe_names"
down_revision = "0033_ambiguous_fish_landlocked"
branch_labels = None
depends_on = None

# name_en -> new name_translations->>'es'
_RENAMES: dict[str, str] = {
    "Celery with hummus": "Apio con crema de garbanzo",
    "Cucumber with hummus": "Pepino con crema de garbanzo",
    "Carrot sticks with hummus": "Palitos de zanahoria con crema de garbanzo",
    "Carrot and cucumber with hummus": "Zanahoria y pepino con crema de garbanzo",
    "Hummus with whole-grain bread and boiled egg": (
        "Crema de garbanzo con pan integral y huevo duro"
    ),
    "Steamed edamame": "Frijoles de soya al vapor",
    "Edamame with lemon": "Frijoles de soya con limón",
    "Spinach Egg-White Breakfast Wrap": "Enrollado de espinaca y clara de huevo",
    "Egg White and Avocado Breakfast Wrap": "Enrollado de claras y aguacate",
    "Egg and Turkey Breakfast Wrap": "Enrollado de huevo y pavo",
    "Tofu and Black Bean Breakfast Skillet": "Tofu salteado con frijol negro",
}


def upgrade() -> None:
    conn = op.get_bind()
    n = 0
    for name_en, name_es in _RENAMES.items():
        res = conn.execute(
            text(
                """
                UPDATE recipes
                   SET name_translations = jsonb_set(
                           name_translations, '{es}', to_jsonb(CAST(:es AS text)), true
                       )
                 WHERE name_en = :en
                """
            ),
            {"es": name_es, "en": name_en},
        )
        n += res.rowcount
    print(f"0034: renamed {n} recipes")  # noqa: T201


def downgrade() -> None:
    # The old names violated the naming rule; restoring them would re-break it.
    # Pre-fix values are in the 2026-07-17 backup if ever needed.
    pass
