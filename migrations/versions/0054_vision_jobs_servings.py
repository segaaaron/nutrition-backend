"""0054 — add servings column to vision_jobs.

Stores how many people the scanned plate is for (1..8, default 1).
Detection items in detected_items JSONB always represent the full plate;
`servings` is applied at presentation time to compute per-serving macros
and at food_log write time to log the individual portion.

DEFAULT 1 backfills all existing rows (solo plate = 1 person).
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0054_vision_jobs_servings"
down_revision = "0053_water_logs_unique_user_time"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "vision_jobs",
        sa.Column("servings", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("vision_jobs", "servings")
