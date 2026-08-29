"""Add plan_meal_items for custom (user-composed) meals.

Revision ID: 0056
Revises: 0055
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID


revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plan_meal_items",
        sa.Column(
            "id",
            PG_UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "plan_meal_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("plan_meals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Nullable: items with no matching food row use free_text_name instead.
        sa.Column(
            "food_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("foods.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("free_text_name", sa.Text, nullable=True),
        sa.Column("grams", sa.Numeric(precision=8, scale=2), nullable=False),
        # Denormalized at write time from the foods row (avoids a JOIN on every read).
        sa.Column("kcal", sa.Integer, nullable=True),
        sa.Column("protein_g", sa.Integer, nullable=True),
        sa.Column("carbs_g", sa.Integer, nullable=True),
        sa.Column("fat_g", sa.Integer, nullable=True),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        sa.CheckConstraint("grams > 0", name="ck_plan_meal_items_grams_positive"),
        sa.CheckConstraint(
            "food_id IS NOT NULL OR free_text_name IS NOT NULL",
            name="ck_plan_meal_items_has_name",
        ),
    )
    op.create_index(
        "ix_plan_meal_items_plan_meal_id",
        "plan_meal_items",
        ["plan_meal_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_plan_meal_items_plan_meal_id", table_name="plan_meal_items")
    op.drop_table("plan_meal_items")
