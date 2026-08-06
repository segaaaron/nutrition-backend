"""0039 — extend meal_time_enum with morning_snack and afternoon_snack.

Revision: 0039_meal_time_five_slots
Author:   nova-backend-architect
Date:     2026-08-06

NOVA plans currently support four meal slots: breakfast, lunch, dinner, snack.
Clinical evidence and LATAM eating culture support five structured eating
occasions for users with obesity (BMI ≥ 30) or fatty liver (MASLD):

  - Springer meta-analysis 2023: the predominant eating pattern for adults
    with obesity is five meals — breakfast, two prepared meals, two snacks.
  - MASLD guidelines (Mayo/AGA 2024): eating fewer than three times per day
    and nighttime fasting over 14 h are direct risk factors. Five structured
    meals space energy intake to prevent hunger-driven overeating.
  - LATAM cultural baseline: Mexico 4 meals (breakfast, media mañana ~10am,
    main meal 2–4pm, evening snack). Brazil: afternoon snack 42–78% adherence.

Adding two distinct sub-slots instead of doubling 'snack' lets the plan
generator assign different kcal targets to each (morning ~8%, afternoon ~8%
of daily target), apply separate recipe pools by weight, and expose them as
named slots in the API so iOS can label them correctly ("Media mañana" /
"Media tarde").

Data migration on recipes:
  - snack + kcal > 130  → morning_snack  (163 recipes, bridges to almuerzo)
  - snack + kcal ≤ 130  → afternoon_snack (154 recipes, light bridge to cena)
  - snack + kcal IS NULL → morning_snack  (safe default — unknown kcal treated
                                           as heavier until recomputed)

plan_meals rows are NOT migrated. Existing active plans keep 'snack' as their
meal_time; 'snack' remains a valid enum value and the plan router still handles
it. Only newly generated plans will use morning_snack / afternoon_snack.

Downgrade: Postgres does not support DROP VALUE on enums. A downgrade would
require recreating the type from scratch while plans referencing the new values
exist — not safe. Manual intervention is required.
"""
from __future__ import annotations

from alembic import op

# ---------------------------------------------------------------------------
# Revision metadata
# ---------------------------------------------------------------------------
revision = "0039_meal_time_five_slots"
down_revision = "0038_recipe_integrity_constraints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Postgres 16 allows ALTER TYPE … ADD VALUE inside a transaction block
    # (restriction lifted in PG 12). IF NOT EXISTS makes this idempotent.
    op.execute("ALTER TYPE meal_time_enum ADD VALUE IF NOT EXISTS 'morning_snack'")
    op.execute("ALTER TYPE meal_time_enum ADD VALUE IF NOT EXISTS 'afternoon_snack'")

    # Re-classify existing snack recipes into the two new sub-slots.
    # kcal > 130: morning snack (heavier — bridges breakfast to lunch).
    op.execute(
        "UPDATE recipes SET meal_time = 'morning_snack' "
        "WHERE meal_time = 'snack' AND kcal > 130"
    )
    # kcal ≤ 130: afternoon snack (lighter — bridges lunch to dinner).
    op.execute(
        "UPDATE recipes SET meal_time = 'afternoon_snack' "
        "WHERE meal_time = 'snack' AND kcal <= 130"
    )
    # kcal IS NULL: default to morning_snack (safe — unknown weight).
    op.execute(
        "UPDATE recipes SET meal_time = 'morning_snack' "
        "WHERE meal_time = 'snack' AND kcal IS NULL"
    )


def downgrade() -> None:
    raise NotImplementedError(
        "Cannot remove enum values in Postgres — manual intervention required. "
        "To downgrade: recreate meal_time_enum without morning_snack/afternoon_snack, "
        "reassign all affected rows back to 'snack', then drop the old type."
    )
