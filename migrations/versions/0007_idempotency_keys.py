"""idempotency_keys table — DB fallback when Redis is cold/restarted"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006_billing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "idempotency_keys",
        sa.Column("key", sa.Text, primary_key=True),
        sa.Column("response_body", sa.JSON, nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
    )
    op.create_index(
        "idx_idempotency_keys_expires_at",
        "idempotency_keys", ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_idempotency_keys_expires_at", table_name="idempotency_keys")
    op.drop_table("idempotency_keys")
