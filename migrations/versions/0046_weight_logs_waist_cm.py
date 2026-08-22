"""0046 — Add waist_cm to weight_logs + food_log_ids to vision_jobs + i18n 500.

B1:  waist_cm was added to 0001_init.py CREATE TABLE after PROD already applied
     that migration. `GET /me/weight-goal` fails with ProgrammingError → 500.
B7:  Add food_log_ids JSONB column to vision_jobs so `GET /logs/food/jobs/{id}`
     can return which food_log rows this scan created.
B12: Seed i18n translations for the generic 500 error.

Revision: 0046_weight_logs_waist_cm
"""

from alembic import op

revision = "0046_weight_logs_waist_cm"
down_revision = "0045_fasting_preferences_and_i18n"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # B1: IF NOT EXISTS is safe even on fresh installs where 0001 already had the column.
    op.execute(
        """
        ALTER TABLE weight_logs
          ADD COLUMN IF NOT EXISTS waist_cm numeric NULL
        """
    )

    # B7: food_log_ids — list of UUIDs created by the scan (empty when persist=false)
    op.execute(
        """
        ALTER TABLE vision_jobs
          ADD COLUMN IF NOT EXISTS food_log_ids jsonb NULL
        """
    )

    # QA Fix #1: method_h CHECK constraint in 0001 only covers (16,18,20).
    # Protocol 14_10 maps to method_h=14 → INSERT fails with CHECK violation.
    # Drop old constraint (auto-named) and recreate to include 14.
    op.execute(
        """
        DO $$
        DECLARE
          cname text;
        BEGIN
          SELECT conname INTO cname
            FROM pg_constraint
           WHERE conrelid = 'fasting_sessions'::regclass
             AND contype = 'c'
             AND pg_get_constraintdef(oid) LIKE '%method_h%';
          IF cname IS NOT NULL THEN
            EXECUTE 'ALTER TABLE fasting_sessions DROP CONSTRAINT ' || quote_ident(cname);
          END IF;
        END;
        $$
        """
    )
    op.execute(
        """
        ALTER TABLE fasting_sessions
          ADD CONSTRAINT ck_fasting_sessions_method_h
          CHECK (method_h IN (14, 16, 18, 20))
        """
    )

    # B12: i18n for internal_server_error (500 generic handler)
    op.execute(
        """
        INSERT INTO i18n_translations (scope, key, locale, value) VALUES
          ('error', 'internal_server_error.title', 'es', 'Error interno del servidor'),
          ('error', 'internal_server_error.title', 'en', 'Internal server error'),
          ('error', 'internal_server_error.detail', 'es', 'Ocurrió un error inesperado. Intenta de nuevo en un momento.'),
          ('error', 'internal_server_error.detail', 'en', 'An unexpected error occurred. Please try again later.')
        ON CONFLICT (scope, key, locale) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE weight_logs DROP COLUMN IF EXISTS waist_cm")
    op.execute("ALTER TABLE vision_jobs DROP COLUMN IF EXISTS food_log_ids")
    # Restore old CHECK (16,18,20 only)
    op.execute("ALTER TABLE fasting_sessions DROP CONSTRAINT IF EXISTS ck_fasting_sessions_method_h")
    op.execute(
        "ALTER TABLE fasting_sessions ADD CONSTRAINT ck_fasting_sessions_method_h CHECK (method_h IN (16, 18, 20))"
    )
    op.execute(
        """
        DELETE FROM i18n_translations
         WHERE scope = 'error' AND key LIKE 'internal_server_error.%'
        """
    )
