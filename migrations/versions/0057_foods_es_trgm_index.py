"""0057 — GIN trigram index on foods Spanish name for search.

Revision ID: 0057
Revises: 0056
"""

from alembic import op

revision = "0057"
down_revision = "0056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_foods_name_es_trgm "
        "ON foods USING gin ((lower(name_translations->>'es')) gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_foods_name_es_trgm")
