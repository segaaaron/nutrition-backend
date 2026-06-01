"""user_profiles onboarding extensions — dietary_pattern, bodyfat_pct, trimester, lactation

Adds four NULLABLE columns required by the mobile onboarding contract
(docs/mobile/ONBOARDING_API_CONTRACT.md). All columns are nullable for
backward compatibility with existing profile rows; values will be populated
incrementally as users complete the extended onboarding flow.

CHECK constraints enforce enum/range invariants at the DB boundary (defence
in depth — domain layer also validates). Partial index on `dietary_pattern`
supports the recipe-filter query pattern (WHERE dietary_pattern = ?).

Plain CREATE INDEX is acceptable at current user-table size. Switch to
CONCURRENTLY in a follow-up once row count exceeds ~100k.
"""
from alembic import op
import sqlalchemy as sa

revision = "0010_user_profile_onboarding_extensions"
down_revision = "0009_plan_algorithm_infra"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Nullable columns (backward-compatible with existing rows) ---
    op.add_column(
        "user_profiles",
        sa.Column("dietary_pattern", sa.Text(), nullable=True),
    )
    op.add_column(
        "user_profiles",
        sa.Column("bodyfat_pct", sa.Numeric(4, 2), nullable=True),
    )
    op.add_column(
        "user_profiles",
        sa.Column("trimester", sa.Text(), nullable=True),
    )
    op.add_column(
        "user_profiles",
        sa.Column("is_exclusively_breastfeeding", sa.Boolean(), nullable=True),
    )

    # --- CHECK constraints (enum + range invariants) ---
    op.create_check_constraint(
        "ck_user_profiles_dietary_pattern",
        "user_profiles",
        "dietary_pattern IS NULL OR dietary_pattern IN "
        "('omnivore', 'pescatarian', 'vegetarian', 'vegan')",
    )
    op.create_check_constraint(
        "ck_user_profiles_bodyfat_pct",
        "user_profiles",
        "bodyfat_pct IS NULL OR (bodyfat_pct BETWEEN 3 AND 60)",
    )
    op.create_check_constraint(
        "ck_user_profiles_trimester",
        "user_profiles",
        "trimester IS NULL OR trimester IN ('first', 'second', 'third')",
    )

    # --- Partial index for dietary_pattern filter queries ---
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_profiles_dietary_pattern "
        "ON user_profiles (dietary_pattern) "
        "WHERE dietary_pattern IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_user_profiles_dietary_pattern")

    op.drop_constraint(
        "ck_user_profiles_trimester", "user_profiles", type_="check"
    )
    op.drop_constraint(
        "ck_user_profiles_bodyfat_pct", "user_profiles", type_="check"
    )
    op.drop_constraint(
        "ck_user_profiles_dietary_pattern", "user_profiles", type_="check"
    )

    op.drop_column("user_profiles", "is_exclusively_breastfeeding")
    op.drop_column("user_profiles", "trimester")
    op.drop_column("user_profiles", "bodyfat_pct")
    op.drop_column("user_profiles", "dietary_pattern")
