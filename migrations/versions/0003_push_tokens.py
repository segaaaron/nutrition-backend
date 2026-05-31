"""0003 — push_tokens table (Sprint 6.A) + push_platform_enum."""
from __future__ import annotations

from alembic import op

revision = "0003_push_tokens"
down_revision = "0002_vision_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE TYPE push_platform_enum AS ENUM ('web','ios','android')")
    op.execute("""
        CREATE TABLE push_tokens (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            platform push_platform_enum NOT NULL,
            token text NOT NULL,
            endpoint text NULL,         -- web push
            p256dh text NULL,           -- web push key
            auth text NULL,             -- web push auth secret
            locale char(2) NOT NULL DEFAULT 'en',
            created_at timestamptz NOT NULL DEFAULT now(),
            last_used_at timestamptz NULL,
            invalid_at timestamptz NULL
        )
    """)
    op.execute("CREATE UNIQUE INDEX uq_push_tokens_token ON push_tokens(token)")
    op.execute(
        "CREATE INDEX ix_push_tokens_user ON push_tokens(user_id) "
        "WHERE invalid_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS push_tokens")
    op.execute("DROP TYPE IF EXISTS push_platform_enum")
