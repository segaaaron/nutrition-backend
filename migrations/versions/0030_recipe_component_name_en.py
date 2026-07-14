"""0030 — recipe_components.name_en (English ingredient names, BE-9).

Revision: 0030_recipe_component_name_en
Author:   nova-backend-architect
Date:     2026-07-13

Adds a nullable ``name_en`` column to ``recipe_components`` and backfills it
from the curated ES->EN map in ``data/ingredient_translations_es_en.json``.

Lookup is case-insensitive on ``lower(trim(free_text_name))`` so both the
capitalised and lowercase variants of the same ingredient resolve to the same
English string. Rows whose ``free_text_name`` has no translation stay NULL —
the API falls back to ``free_text_name`` (mostly ES), so nothing breaks.

Idempotent: only fills rows where ``name_en IS NULL``.
"""
from __future__ import annotations

import json
from pathlib import Path

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision = "0030_recipe_component_name_en"
down_revision = "0029_drop_food_logs_aggregates_daily"
branch_labels = None
depends_on = None

_MAP_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "ingredient_translations_es_en.json"
)


def _load_translations() -> dict[str, str]:
    data = json.loads(_MAP_PATH.read_text(encoding="utf-8"))
    # index case-insensitively on trimmed lowercase key
    return {k.strip().lower(): v for k, v in data["translations"].items()}


def upgrade() -> None:
    op.add_column(
        "recipe_components",
        sa.Column("name_en", sa.Text(), nullable=True),
    )
    conn = op.get_bind()
    translations = _load_translations()
    for es_lower, en in translations.items():
        conn.execute(
            text(
                """
                UPDATE recipe_components
                   SET name_en = :en
                 WHERE name_en IS NULL
                   AND lower(trim(free_text_name)) = :es
                """
            ),
            {"en": en, "es": es_lower},
        )


def downgrade() -> None:
    op.drop_column("recipe_components", "name_en")
