"""0045 — fasting preferences table + i18n seeds for error codes.

Changes:
  1. Add `user_fasting_preferences` table (F1 — iOS fasting preference API).
  2. Add `protocol` VARCHAR(10) + `break_reason` VARCHAR(50) to `fasting_sessions` (F2).
  3. Seed i18n translations for error codes: meal_day_in_future (B9),
     and fasting errors: fasting_not_available, fasting_window_in_future,
     fasting_invalid_protocol, fasting_overlapping_window (F5).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0045_fasting_preferences_and_i18n"
down_revision = "0044_food_logs_plan_method"
branch_labels = None
depends_on = None

# ── i18n seeds ──────────────────────────────────────────────────────────────

_I18N_ERRORS = {
    "meal_day_in_future": {
        "meal_day_in_future.title": {
            "es": "No puedes completar una comida de un día futuro",
            "en": "Cannot complete a meal scheduled for a future day",
        },
        "meal_day_in_future.detail": {
            "es": "Esta comida pertenece a un día que aún no ha llegado.",
            "en": "This meal belongs to a day that has not arrived yet.",
        },
    },
    "fasting_not_available": {
        "fasting_not_available.title": {
            "es": "El ayuno no está disponible para tu perfil",
            "en": "Fasting is not available for your current profile",
        },
        "fasting_not_available.detail": {
            "es": "El ayuno intermitente no se recomienda durante el embarazo o la lactancia.",
            "en": "Intermittent fasting is not recommended during pregnancy or breastfeeding.",
        },
    },
    "fasting_window_in_future": {
        "fasting_window_in_future.title": {
            "es": "La ventana de ayuno no puede estar en el futuro",
            "en": "Fasting window cannot be in the future",
        },
        "fasting_window_in_future.detail": {
            "es": "Solo puedes registrar ayunos que ya terminaron.",
            "en": "You can only log fasting windows that have already ended.",
        },
    },
    "fasting_invalid_protocol": {
        "fasting_invalid_protocol.title": {
            "es": "Protocolo de ayuno inválido",
            "en": "Invalid fasting protocol",
        },
        "fasting_invalid_protocol.detail": {
            "es": "Los protocolos válidos son: 14_10, 16_8, 18_6, 20_4.",
            "en": "Valid protocols are: 14_10, 16_8, 18_6, 20_4.",
        },
    },
    "fasting_overlapping_window": {
        "fasting_overlapping_window.title": {
            "es": "Ya existe un ayuno en ese período",
            "en": "A fasting window already exists for this period",
        },
        "fasting_overlapping_window.detail": {
            "es": "Las ventanas de ayuno no pueden solaparse.",
            "en": "Fasting windows cannot overlap.",
        },
    },
}


def upgrade() -> None:
    # ── 1. user_fasting_preferences ──────────────────────────────────────────
    op.create_table(
        "user_fasting_preferences",
        sa.Column("user_id", sa.UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("protocol", sa.String(10), nullable=True),
        sa.Column("window_start_local", sa.String(5), nullable=True),
        sa.Column("time_zone", sa.String(64), nullable=True),
        sa.Column("reminders_enabled", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.execute(
        "ALTER TABLE user_fasting_preferences "
        "ADD CONSTRAINT ck_fasting_pref_protocol "
        "CHECK (protocol IN ('14_10','16_8','18_6','20_4') OR protocol IS NULL)"
    )

    # ── 2. fasting_sessions: protocol + break_reason ─────────────────────────
    op.add_column("fasting_sessions", sa.Column("protocol", sa.String(10), nullable=True))
    op.add_column("fasting_sessions", sa.Column("break_reason", sa.String(50), nullable=True))
    op.execute(
        "ALTER TABLE fasting_sessions "
        "ADD CONSTRAINT ck_fasting_sessions_protocol "
        "CHECK (protocol IN ('14_10','16_8','18_6','20_4') OR protocol IS NULL)"
    )

    # ── 3. i18n seeds ────────────────────────────────────────────────────────
    conn = op.get_bind()
    for _group_key, entries in _I18N_ERRORS.items():
        for key, by_locale in entries.items():
            for locale, value in by_locale.items():
                conn.execute(
                    sa.text(
                        "INSERT INTO i18n_translations(scope, key, locale, value) "
                        "VALUES ('error', :k, :l, :v) "
                        "ON CONFLICT (scope, key, locale) DO UPDATE SET value = EXCLUDED.value"
                    ),
                    {"k": key, "l": locale, "v": value},
                )


def downgrade() -> None:
    op.drop_table("user_fasting_preferences")
    op.drop_column("fasting_sessions", "break_reason")
    op.drop_column("fasting_sessions", "protocol")
    conn = op.get_bind()
    for _group_key, entries in _I18N_ERRORS.items():
        for key, by_locale in entries.items():
            for locale in by_locale:
                conn.execute(
                    sa.text(
                        "DELETE FROM i18n_translations "
                        "WHERE scope = 'error' AND key = :k AND locale = :l"
                    ),
                    {"k": key, "l": locale},
                )
