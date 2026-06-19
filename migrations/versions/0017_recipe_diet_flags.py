"""0017 — Recipe diet flags (is_vegan / is_vegetarian) for dietary_pattern filtering.

Context
-------
The onboarding form collects ``dietary_pattern`` (omnivore / vegetarian /
vegan) and promises on-screen *"NOVA excluirá del plan los alimentos que no
comes"*. But Layer 1 eligibility (``app/plan/application/layer1_eligibility.py``)
never filtered by it — a vegan user could be served a meat dish. This adds two
denormalised boolean flags so Layer 1 can hard-exclude non-matching recipes.

Values are backfilled **inline in this migration** (atomic with the column
add) by classifying each recipe from its ``recipe_components`` ingredient names
+ ``name_en`` against the meat/fish/dairy/egg lexicon in
``app/recipes/domain/diet_classifier.py``. This is deliberate: ``IS TRUE``
excludes NULL, so shipping the columns WITHOUT data would make every
vegan/vegetarian plan generation yield an empty pool (``plan_generation_
yielded_no_meals``). The backfill must never lag the schema (QA 2026-06-16).
Re-run ``scripts/backfill_diet_flags.py`` after any lexicon improvement.

Fail-safe semantics: ``NULL`` = unclassified ⇒ Layer 1 EXCLUDES the row for
vegan/vegetarian users (``IS TRUE`` predicate). Serving a possibly-animal dish
to a vegan is the unrecoverable error; a narrower pool is recoverable. Same
fail-closed policy as the safety-critical condition gates.

Reversibility: downgrade drops both columns.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017_recipe_diet_flags"
down_revision = "0016_subscriptions_one_active_per_user"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("recipes", sa.Column("is_vegetarian", sa.Boolean(), nullable=True))
    op.add_column("recipes", sa.Column("is_vegan", sa.Boolean(), nullable=True))

    # Atomic backfill (QA 2026-06-16 HIGH): classify from ingredient text so the
    # columns are never all-NULL the moment they exist — otherwise vegan/
    # vegetarian users hit an empty candidate pool. Pure, stable domain logic.
    from app.recipes.domain.diet_classifier import classify_diet

    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            """
            SELECT r.id, r.name_en,
                   COALESCE(string_agg(rc.free_text_name, ' '), '') AS ings
              FROM recipes r
              LEFT JOIN recipe_components rc ON rc.recipe_id = r.id
             GROUP BY r.id, r.name_en
            """
        )
    ).fetchall()
    upd = sa.text("UPDATE recipes SET is_vegetarian = :v, is_vegan = :vg WHERE id = :id")
    for rid, name, ings in rows:
        blob = f"{name or ''} {ings or ''}".strip()
        if not blob:
            continue  # leave NULL → excluded for veg users (fail-safe)
        is_veg, is_vegan = classify_diet(blob)
        conn.execute(upd, {"v": is_veg, "vg": is_vegan, "id": rid})


def downgrade() -> None:
    op.drop_column("recipes", "is_vegan")
    op.drop_column("recipes", "is_vegetarian")
