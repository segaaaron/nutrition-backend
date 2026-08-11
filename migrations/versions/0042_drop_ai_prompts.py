"""0042 — drop ai_prompts table

Revision: 0042_drop_ai_prompts
Down: 0041_food_logs_fiber_sugar

The ai_prompts table was created in migration 0001 but is never read.
The coach uses a hardcoded system_prompt_for() in app/coach/application/chat_message.py.
The table was left empty in PROD after a TRUNCATE CASCADE in the 2026-08-09 session.
"""

import sqlalchemy as sa
from alembic import op

revision = "0042_drop_ai_prompts"
down_revision = "0041_food_logs_fiber_sugar"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("ai_prompts")


def downgrade() -> None:
    op.create_table(
        "ai_prompts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("context", sa.Text(), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
