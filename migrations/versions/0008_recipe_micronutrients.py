"""recipes micronutrient columns + missing GIN index on contraindicated_conditions

All micronutrient columns are NULLABLE so existing catalog rows are not invalidated.
`pregnancy_safe` is NOT NULL with default FALSE — explicit allow-list (deny by default).

GIN indexes for regions/allergens/tags/target_goals already exist (0001_init).
Only contraindicated_conditions GIN is added here.

At catalog scale (~2k rows) plain CREATE INDEX is acceptable. A follow-up migration
should switch to CREATE INDEX CONCURRENTLY (transactional=False) once the catalog
grows past ~50k rows.
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_recipe_micronutrients"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Micronutrient columns (all NULLABLE except pregnancy_safe) ---
    op.add_column("recipes", sa.Column("gi", sa.SmallInteger(), nullable=True))
    op.add_column("recipes", sa.Column("gl", sa.Numeric(6, 2), nullable=True))
    op.add_column("recipes", sa.Column("potassium_mg", sa.Integer(), nullable=True))
    op.add_column("recipes", sa.Column("phosphorus_mg", sa.Integer(), nullable=True))
    op.add_column("recipes", sa.Column("iron_mg", sa.Numeric(6, 2), nullable=True))
    op.add_column("recipes", sa.Column("heme_pct", sa.Numeric(4, 2), nullable=True))
    op.add_column("recipes", sa.Column("calcium_mg", sa.Integer(), nullable=True))
    op.add_column("recipes", sa.Column("omega3_mg", sa.Integer(), nullable=True))
    op.add_column("recipes", sa.Column("folate_ug", sa.Integer(), nullable=True))
    op.add_column(
        "recipes",
        sa.Column(
            "pregnancy_safe",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # --- CHECK constraints ---
    op.create_check_constraint(
        "ck_recipes_gi_range",
        "recipes",
        "gi IS NULL OR (gi BETWEEN 0 AND 110)",
    )
    op.create_check_constraint(
        "ck_recipes_heme_pct_range",
        "recipes",
        "heme_pct IS NULL OR (heme_pct BETWEEN 0 AND 100)",
    )
    op.create_check_constraint(
        "ck_recipes_gl_nonneg",
        "recipes",
        "gl IS NULL OR gl >= 0",
    )
    op.create_check_constraint(
        "ck_recipes_iron_nonneg",
        "recipes",
        "iron_mg IS NULL OR iron_mg >= 0",
    )

    # --- Missing GIN index on contraindicated_conditions ---
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_recipes_contraindicated_conditions "
        "ON recipes USING gin (contraindicated_conditions)"
    )

    # --- Filter index for pregnancy-safe lookups (deny-by-default → only true matters) ---
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_recipes_pregnancy_safe "
        "ON recipes (pregnancy_safe) WHERE pregnancy_safe = true"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_recipes_pregnancy_safe")
    op.execute("DROP INDEX IF EXISTS ix_recipes_contraindicated_conditions")

    op.drop_constraint("ck_recipes_iron_nonneg", "recipes", type_="check")
    op.drop_constraint("ck_recipes_gl_nonneg", "recipes", type_="check")
    op.drop_constraint("ck_recipes_heme_pct_range", "recipes", type_="check")
    op.drop_constraint("ck_recipes_gi_range", "recipes", type_="check")

    op.drop_column("recipes", "folate_ug")
    op.drop_column("recipes", "omega3_mg")
    op.drop_column("recipes", "calcium_mg")
    op.drop_column("recipes", "heme_pct")
    op.drop_column("recipes", "iron_mg")
    op.drop_column("recipes", "phosphorus_mg")
    op.drop_column("recipes", "potassium_mg")
    op.drop_column("recipes", "gl")
    op.drop_column("recipes", "gi")
    # NOT NULL column dropped last
    op.drop_column("recipes", "pregnancy_safe")
