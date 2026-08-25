"""0049 — Unique index: one progress photo per (user_id, image_url).

The SHA-256 hash was already computed before insertion but not used to
prevent duplicates. A retry or double-upload produced two rows with the
same URL and the gallery showed the photo twice.

Reported by iOS on 2026-08-24 (§2bis.4 of INFORME-BACKEND-2026-08-24.md).

Revision: 0049_progress_photos_unique_url
"""

from alembic import op

revision = "0049_progress_photos_unique_url"
down_revision = "0048_grocery_list_unique_plan"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Deduplicate any existing rows first (keep the earliest per pair).
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY user_id, image_url ORDER BY taken_at, id
                   ) AS rn
              FROM progress_photos
             WHERE image_url IS NOT NULL
        )
        DELETE FROM progress_photos
         WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
        """
    )

    op.execute(
        """
        CREATE UNIQUE INDEX ix_progress_photos_unique_url
            ON progress_photos(user_id, image_url)
         WHERE image_url IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_progress_photos_unique_url")
