"""Vision precision: user_portion_calibration + vision_accuracy_log tables.

Revision: 0024_vision_portion_accuracy
Author:   nova-api-expert
Date:     2026-07-08

user_portion_calibration
  Stores per-user, per-food-group portion correction ratios learned from
  the user's own corrections (corrected_g / estimated_g). Applied in
  _match_and_ground to calibrate unmatched items before macro grounding.

vision_accuracy_log
  Tracks detected vs user-corrected kcal so we can measure precision
  over time per food_group and match_method. Not user-facing — ops only.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024_vision_portion_accuracy"
down_revision = "0023_plan_locale"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_portion_calibration",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("food_group", sa.Text(), nullable=False),
        sa.Column(
            "correction_ratio",
            sa.Numeric(precision=6, scale=3),
            nullable=False,
            comment="Rolling avg of (corrected_g / estimated_g) per food_group",
        ),
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("user_id", "food_group"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "vision_accuracy_log",
        sa.Column(
            "id",
            sa.UUID(),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("food_group", sa.Text(), nullable=True),
        sa.Column("match_method", sa.Text(), nullable=True),
        sa.Column("kcal_detected", sa.Integer(), nullable=True),
        sa.Column("kcal_corrected", sa.Integer(), nullable=True),
        sa.Column(
            "error_pct",
            sa.Numeric(precision=7, scale=2),
            nullable=True,
            comment="(corrected - detected) / detected * 100",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_vision_accuracy_log_user_created",
        "vision_accuracy_log",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_vision_accuracy_log_user_created", table_name="vision_accuracy_log")
    op.drop_table("vision_accuracy_log")
    op.drop_table("user_portion_calibration")
