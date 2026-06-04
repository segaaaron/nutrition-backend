"""Integration — CRITICAL-2: cross-user cache hits MUST NOT leak
matched_food_id (which is per-user personal foods).

Scenario:
  - User A submits a photo, matcher resolves to personal food X.
  - User B submits the same photo (same SHA) — repo returns a cache hit
    BUT with matched_food_id stripped. The ProcessVisionJob use case then
    re-runs the matcher against User B's catalog, producing User B's own
    match (or unmatched).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text

from app.vision.infrastructure.repositories import SqlVisionJobRepository

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_cross_user_cache_hit_strips_personal_match(
    db_session: Any,
    fake_user_id: UUID,
) -> None:
    # User A's job, completed with a personal match to food_id X.
    user_a = fake_user_id  # FK target
    sha = "d" * 64
    user_a_match_food = uuid.uuid4()
    items_with_pii = json.dumps(
        [
            {
                "name": "homemade granola",
                "estimated_amount_g": 60.0,
                "kcal": 280,
                "protein_g": 6,
                "carbs_g": 35,
                "fat_g": 12,
                "confidence": 0.85,
                "matched_food_id": str(user_a_match_food),  # User A's personal food
                "matched_name_norm": "homemade granola",
                "match_method": "personal",
            }
        ]
    )
    await db_session.execute(
        text(
            """
        INSERT INTO vision_jobs (
            id, user_id, meal_time, status, image_sha256, image_bytes,
            prompt_sha256, detected_items, created_at
        ) VALUES (
            :id, :uid, 'breakfast', 'completed', :sha, 1000,
            'prompt-v1', CAST(:items AS jsonb), :now
        )
        """
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": str(user_a),
            "sha": sha,
            "items": items_with_pii,
            "now": datetime.now(UTC),
        },
    )
    await db_session.commit()

    repo = SqlVisionJobRepository(db_session)
    # User B (different user) queries the cache.
    out = await repo.find_recent_completed_by_sha(
        image_sha256=sha,
        ttl_days=14,
        current_prompt_sha256="prompt-v1",
    )
    assert out is not None
    items, prompt_sha = out

    # The LLM detection (image-bound, shareable) is preserved.
    assert items[0].name == "homemade granola"
    assert items[0].kcal == 280

    # User A's personal match is STRIPPED before being returned to User B.
    assert (
        items[0].matched_food_id is None
    ), "PII leak: matched_food_id from user A leaked through cache to user B"
    assert items[0].matched_name_norm is None
    assert items[0].match_method is None


@pytest.mark.asyncio
async def test_cache_miss_returns_none_for_unknown_sha(db_session: Any) -> None:
    repo = SqlVisionJobRepository(db_session)
    out = await repo.find_recent_completed_by_sha(
        image_sha256="f" * 64,
        ttl_days=14,
    )
    assert out is None
