"""0002 — vision_jobs table + coach_faq (pgvector) + recipes.coach_story_translations.

Vision IA bounded context persistence (spec §9.1, §7 patch). Coach RAG FAQ
table seeded by `scripts/seed_coach_faq.py` (deferred). Recipe story
narratives live in `recipes.coach_story_translations jsonb` and are filled
by the nightly Arq backfill `coach_recipe_story_backfill`.
"""
from __future__ import annotations

from alembic import op

revision = "0002_vision_jobs"
down_revision = "0001_init"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enum for job state.
    op.execute(
        "CREATE TYPE vision_job_status_enum AS ENUM "
        "('queued','running','completed','failed','cancelled')"
    )

    op.execute("""
        CREATE TABLE vision_jobs (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            meal_time meal_time_enum NOT NULL,
            status vision_job_status_enum NOT NULL DEFAULT 'queued',
            image_sha256 text NOT NULL,
            image_bytes int NOT NULL,
            idempotency_key text NULL,
            prompt_sha256 text NULL,
            detected_items jsonb NULL,
            error_code text NULL,
            error_detail text NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            started_at timestamptz NULL,
            completed_at timestamptz NULL
        )
    """)
    op.execute("CREATE INDEX ix_vision_jobs_user_created ON vision_jobs(user_id, created_at DESC)")
    op.execute("CREATE INDEX ix_vision_jobs_status ON vision_jobs(status) WHERE status IN ('queued','running')")
    op.execute(
        "CREATE UNIQUE INDEX uq_vision_jobs_idem "
        "ON vision_jobs(user_id, idempotency_key) WHERE idempotency_key IS NOT NULL"
    )

    # Coach FAQ embeddings table (RAG, Camino 2).
    op.execute("""
        CREATE TABLE coach_faq (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            question_en text NOT NULL,
            answer_translations jsonb NOT NULL DEFAULT '{}'::jsonb,
            intent text NULL,
            embedding vector(1536) NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX ix_coach_faq_embedding ON coach_faq "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 100)"
    )

    # Recipe coach story narrative cache (feature F).
    op.execute(
        "ALTER TABLE recipes "
        "ADD COLUMN IF NOT EXISTS coach_story_translations jsonb NOT NULL DEFAULT '{}'::jsonb"
    )

    # Personal vision corrections (feature E learn_user_correction).
    op.execute("""
        CREATE TABLE vision_user_corrections (
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            detected_name_norm text NOT NULL,
            corrected_food_id uuid NULL REFERENCES foods(id) ON DELETE SET NULL,
            corrected_amount_g numeric NULL,
            occurrences int NOT NULL DEFAULT 1,
            last_seen_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, detected_name_norm)
        )
    """)

    # Dead-letter table for failed cron / arq jobs (mandatory validation #10).
    op.execute("""
        CREATE TABLE job_deadletter (
            id bigserial PRIMARY KEY,
            task_name text NOT NULL,
            args jsonb NULL,
            error text NOT NULL,
            attempts int NOT NULL DEFAULT 0,
            failed_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_job_deadletter_task ON job_deadletter(task_name, failed_at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS job_deadletter")
    op.execute("DROP TABLE IF EXISTS vision_user_corrections")
    op.execute("ALTER TABLE recipes DROP COLUMN IF EXISTS coach_story_translations")
    op.execute("DROP TABLE IF EXISTS coach_faq")
    op.execute("DROP TABLE IF EXISTS vision_jobs")
    op.execute("DROP TYPE IF EXISTS vision_job_status_enum")
