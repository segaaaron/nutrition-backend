"""0005 — achievements catalog table + seed.

The original `achievements` table (migration 0001) tracks user-unlocks. The
*catalog* lives in code (`app.gamification.domain.catalog`) so we don't need
a separate DB table for it — but we surface a thin `achievements_catalog`
view of (code, points, icon) for analytics and admin tooling.
"""
from __future__ import annotations

from alembic import op

revision = "0005_achievements_seed"
down_revision = "0004_food_log_aggregates"
branch_labels = None
depends_on = None

# Snapshot of the catalog at seed time. Kept in sync manually with
# app.gamification.domain.catalog.CATALOG (single source of truth in code).
CATALOG_SEED: list[tuple[str, int, str]] = [
    ("first_meal_logged", 10, "spoon"),
    ("streak_3d", 25, "fire"),
    ("streak_7d", 50, "fire"),
    ("streak_14d", 100, "fire"),
    ("streak_30d", 200, "fire"),
    ("streak_100d", 500, "fire"),
    ("first_fasting_16h", 30, "moon"),
    ("first_fasting_18h", 40, "moon"),
    ("first_fasting_20h", 60, "moon"),
    ("fasting_streak_7d", 100, "moon"),
    ("protein_goal_7d", 80, "muscle"),
    ("water_goal_7d", 60, "drop"),
    ("first_recipe_swapped", 15, "shuffle"),
    ("plan_completed_week", 150, "calendar"),
    ("plan_completed_month", 500, "calendar"),
    ("early_bird", 40, "sun"),
    ("weekend_warrior", 50, "shield"),
    ("meal_variety_30", 120, "leaf"),
    ("vision_logs_10", 30, "camera"),
    ("voice_logs_5", 20, "mic"),
    ("first_weight_log", 10, "scale"),
    ("weight_log_streak_14d", 70, "scale"),
    ("first_grocery_list", 15, "cart"),
    ("kcal_within_tolerance_7d", 80, "target"),
    ("micronutrient_perfect_day", 90, "star"),
    ("coach_first_chat", 10, "chat"),
    ("plan_recalibrated", 30, "compass"),
    ("photo_progress_first", 10, "photo"),
    ("comeback_kid", 25, "heart"),
    ("night_owl_3", 15, "moon-stars"),
    ("level_5", 0, "trophy"),
    ("level_10", 0, "trophy"),
]


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS achievements_catalog (
            code text PRIMARY KEY,
            points int NOT NULL,
            icon text NOT NULL
        )
    """)
    for code, points, icon in CATALOG_SEED:
        op.execute(
            "INSERT INTO achievements_catalog (code, points, icon) "
            f"VALUES ('{code}', {points}, '{icon}') "
            "ON CONFLICT (code) DO UPDATE SET points = EXCLUDED.points, icon = EXCLUDED.icon"
        )

    # Seed feature flags relevant to Sprint 7+8.
    op.execute("""
        INSERT INTO feature_flags (key, enabled, rollout_pct, description) VALUES
          ('leaderboard_enabled',           false, 0,
           'Country-scoped weekly leaderboard. Gated until anti-cheat lands.'),
          ('coach_proactive_alerts',        true,  100,
           'Coach pushes proactive nudges (Sprint 6 feature G).'),
          ('vision_2_tier_optimization',    true,  100,
           'Vision uses cheap tier first, escalates only on low-confidence.'),
          ('grocery_share_links',           true,  100,
           'Grocery list signed-share URLs (Sprint 7.C).'),
          ('billing_trial_enabled',         true,  100,
           '14-day premium trial on signup.')
        ON CONFLICT (key) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS achievements_catalog")
    for k in (
        "leaderboard_enabled", "coach_proactive_alerts",
        "vision_2_tier_optimization", "grocery_share_links",
        "billing_trial_enabled",
    ):
        op.execute(f"DELETE FROM feature_flags WHERE key = '{k}'")
