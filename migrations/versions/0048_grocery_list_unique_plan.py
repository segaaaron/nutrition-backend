"""0048 — Unique index: one grocery list per plan.

Enforces the invariant that a plan can have at most one grocery list.
``get_or_create_list`` does a read-then-write which is a known race: two
simultaneous GET /plans/{id}/grocery-list requests both read no list and
both insert, producing two lists for the same plan.

Reported by iOS on 2026-08-24 (§2bis.1 of INFORME-BACKEND-2026-08-24.md).

Pre-flight deduplicates any existing plans with two lists, keeping the
most recently generated one (same logic ``get_or_create_list`` uses via
ORDER BY generated_at DESC LIMIT 1).

Revision: 0048_grocery_list_unique_plan
"""

from alembic import op

revision = "0048_grocery_list_unique_plan"
down_revision = "0047_fasting_one_active_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Keep the most recently generated list per plan; delete the rest.
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY plan_id ORDER BY generated_at DESC, id
                   ) AS rn
              FROM grocery_lists
        )
        DELETE FROM grocery_lists
         WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
        """
    )

    op.execute(
        """
        CREATE UNIQUE INDEX ix_grocery_list_one_per_plan
            ON grocery_lists(plan_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_grocery_list_one_per_plan")
