"""Recipe excluded_countries: per-recipe country exclusion list.

Revision: 0025_recipe_excluded_countries
Author:   nova-api-expert
Date:     2026-07-08

Adds `excluded_countries TEXT[] NOT NULL DEFAULT '{}'` to the `recipes` table
so individual recipes can carry an explicit list of ISO-3166-1 alpha-2 country
codes where the recipe must NOT be served.

Primary use-case: sea-fish and seafood recipes that should be excluded for
landlocked countries (BO=Bolivia, PY=Paraguay) per CLAUDE.md §REGLA PAÍSES
SIN MAR. The column is populated by data-ops / catalog scripts; Layer 1 of
the plan generator filters it via NOT (:country = ANY(excluded_countries)).

A GIN index is added because the `= ANY(column)` operator on TEXT[] uses an
index scan when a GIN index is present. Without GIN the planner does a
seq-scan; with it the plan is an index-only bitmap scan.

The empty-array default (`'{}'`) makes the filter a no-op for the existing
catalog: `NOT (:country = ANY('{}'))` always evaluates to TRUE.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

revision = "0025_recipe_excluded_countries"
down_revision = "0024_vision_portion_accuracy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    # Idempotent: DDL may have been applied manually before alembic_version
    # was advanced (e.g., emergency hotfix directly on VPS). Skip silently.
    existing_cols = {c["name"] for c in inspector.get_columns("recipes")}
    if "excluded_countries" not in existing_cols:
        op.add_column(
            "recipes",
            sa.Column(
                "excluded_countries",
                sa.ARRAY(sa.Text()),
                nullable=False,
                server_default="{}",
                comment=(
                    "ISO-3166-1 alpha-2 codes of countries where this recipe "
                    "must NOT be served. Empty array = available everywhere. "
                    "Used by plan Layer 1 to block sea-fish in landlocked markets."
                ),
            ),
        )

    # GIN index: required for efficient NOT (:country = ANY(excluded_countries))
    existing_indexes = {i["name"] for i in inspector.get_indexes("recipes")}
    if "ix_recipes_excluded_countries" not in existing_indexes:
        op.create_index(
            "ix_recipes_excluded_countries",
            "recipes",
            ["excluded_countries"],
            postgresql_using="gin",
        )


def downgrade() -> None:
    op.drop_index("ix_recipes_excluded_countries", table_name="recipes")
    op.drop_column("recipes", "excluded_countries")
