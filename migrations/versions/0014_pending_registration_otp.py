"""0014 — Allow pending registration OTPs without a user row.

Adds nullable registration metadata to ``otp_codes`` so the signup flow can
persist an OTP before the final ``users`` row exists. This enables the
requested contract: ``POST /auth/register`` creates a pending registration
and only proves the user after valid OTP verification.

Reversibility: additive nullable columns + index. Downgrade drops the index
and the two columns. Existing OTP rows continue to work because the new
columns are nullable.
"""

from __future__ import annotations

from alembic import op

revision = "0014_pending_registration_otp"
down_revision = "0013_leaderboard_anti_cheat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE otp_codes ALTER COLUMN user_id DROP NOT NULL")
    op.execute("ALTER TABLE otp_codes ADD COLUMN IF NOT EXISTS email CITEXT NULL")
    op.execute("ALTER TABLE otp_codes ADD COLUMN IF NOT EXISTS password_hash TEXT NULL")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_otp_codes_email_purpose ON otp_codes (email, purpose)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_otp_codes_email_purpose")
    op.execute("ALTER TABLE otp_codes DROP COLUMN IF EXISTS password_hash")
    op.execute("ALTER TABLE otp_codes DROP COLUMN IF EXISTS email")
    op.execute("DELETE FROM otp_codes WHERE user_id IS NULL")
    op.execute("ALTER TABLE otp_codes ALTER COLUMN user_id SET NOT NULL")
