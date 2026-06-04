"""0013 — ADR-0026 leaderboard anti-cheat (L1 tables + vision pHash column).

Adds the storage primitives required by Layer 1 of the leaderboard
anti-cheat plan (synchronous caps, region pinning, append-only audit)
plus an additive nullable `phash_64` column on `vision_jobs` reserved
for the deferred Layer 2 perceptual-hash clustering job.

Schema added:

  - `profile_region_change_audit`   — append-only region change log;
    feeds the 30-day immutability gate in `UpdateProfile`.
  - `gamification_shadow_ban`       — current shadow-ban state (one row
    per user); read by the deferred L3 ZADD gate.
  - `leaderboard_audit`             — append-only XP-award audit;
    idempotency_key UNIQUE prevents double-credit on retries.
  - `vision_jobs.phash_64 BIGINT`   — nullable, no backfill; populated
    by the future L2 worker, indexed for Hamming-distance candidate
    lookups.
  - Feature flag `leaderboard_l1_caps_enabled` (default FALSE) —
    sub-flag under `leaderboard_enabled`; flipped only after the
    7-gate rollout in ADR-0026 passes.

Reversibility: downgrade drops the four objects in reverse order plus
the feature flag. Additive nullable column → zero-downtime on upgrade,
safe to drop on downgrade.
"""

from __future__ import annotations

from alembic import op

revision = "0013_leaderboard_anti_cheat"
down_revision = "0012_nutritional_goals_active_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Region change audit (append-only).
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS profile_region_change_audit (
            id          BIGSERIAL PRIMARY KEY,
            user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            old_region  TEXT,
            new_region  TEXT NOT NULL,
            changed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_region_change_audit_user_changed
        ON profile_region_change_audit (user_id, changed_at DESC)
        """
    )

    # 2. Shadow-ban current state (one row per banned user).
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS gamification_shadow_ban (
            id          BIGSERIAL PRIMARY KEY,
            user_id     UUID NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
            banned_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            reason      TEXT NOT NULL,
            score       INTEGER NOT NULL DEFAULT 0,
            lifted_at   TIMESTAMPTZ NULL
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_shadow_ban_active
        ON gamification_shadow_ban (user_id)
        WHERE lifted_at IS NULL
        """
    )

    # 3. Append-only XP-award audit. idempotency_key UNIQUE protects
    #    against double-credit when an event is replayed by the bus.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS leaderboard_audit (
            id              BIGSERIAL PRIMARY KEY,
            user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            action          TEXT NOT NULL,
            xp_delta        INTEGER NOT NULL,
            source          TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_leaderboard_audit_user_created
        ON leaderboard_audit (user_id, created_at DESC)
        """
    )

    # 4. pHash column on vision_jobs — nullable, populated by deferred L2.
    op.execute(
        "ALTER TABLE vision_jobs ADD COLUMN IF NOT EXISTS phash_64 BIGINT NULL"
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_vision_jobs_phash
        ON vision_jobs (phash_64)
        WHERE phash_64 IS NOT NULL
        """
    )

    # 5. Sub-flag for L1 caps. Default OFF until 7-gate validation passes.
    op.execute(
        """
        INSERT INTO feature_flags (key, enabled, rollout_pct, description) VALUES
          ('leaderboard_l1_caps_enabled', false, 0,
           'ADR-0026 Layer 1 caps + region pinning. Gated until 7-gate rollout passes.')
        ON CONFLICT (key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM feature_flags WHERE key = 'leaderboard_l1_caps_enabled'")
    op.execute("DROP INDEX IF EXISTS ix_vision_jobs_phash")
    op.execute("ALTER TABLE vision_jobs DROP COLUMN IF EXISTS phash_64")
    op.execute("DROP INDEX IF EXISTS ix_leaderboard_audit_user_created")
    op.execute("DROP TABLE IF EXISTS leaderboard_audit")
    op.execute("DROP INDEX IF EXISTS ix_shadow_ban_active")
    op.execute("DROP TABLE IF EXISTS gamification_shadow_ban")
    op.execute("DROP INDEX IF EXISTS ix_region_change_audit_user_changed")
    op.execute("DROP TABLE IF EXISTS profile_region_change_audit")
