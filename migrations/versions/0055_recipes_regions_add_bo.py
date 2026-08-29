"""Extend ck_recipes_regions_vocab to include 'bo' (Bolivia) and 'py' (Paraguay).

Revision ID: 0055
Revises: 0054
"""

from alembic import op

revision = "0055"
down_revision = "0054"
branch_labels = None
depends_on = None

_VALID_REGIONS = ["latam", "us", "ca", "bo", "py"]
_ARRAY_LITERAL = "ARRAY[" + ",".join(f"'{r}'" for r in _VALID_REGIONS) + "]::char(5)[]"


def upgrade() -> None:
    op.execute("ALTER TABLE recipes DROP CONSTRAINT IF EXISTS ck_recipes_regions_vocab")
    op.execute(
        f"ALTER TABLE recipes ADD CONSTRAINT ck_recipes_regions_vocab "
        f"CHECK (regions IS NULL OR regions <@ {_ARRAY_LITERAL})"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE recipes DROP CONSTRAINT IF EXISTS ck_recipes_regions_vocab")
    op.execute(
        "ALTER TABLE recipes ADD CONSTRAINT ck_recipes_regions_vocab "
        "CHECK (regions IS NULL OR regions <@ ARRAY['latam','us','ca']::char(5)[])"
    )
