"""Integration — SHA256 dedup cache uses the partial index from migration 0011.

Requires Docker. Skip with `-m 'not integration'`.

We insert ~100 vision_jobs rows (mixed statuses + SHAs), then run the cache
lookup and assert the query plan uses `ix_vision_jobs_sha_recent` (the partial
index from migration 0011) rather than a Seq Scan.
"""

from __future__ import annotations

import json
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text

from app.vision.infrastructure.repositories import SqlVisionJobRepository

pytestmark = pytest.mark.integration


async def _seed_jobs(
    session: Any,
    user_id: UUID,
    n: int,
    target_sha: str | None = None,
) -> None:
    """Insert n rows: half completed (with detected_items), half failed/running.
    One row gets `target_sha` so we have a guaranteed hit candidate.
    """
    for i in range(n):
        status = "completed" if i % 2 == 0 else "failed"
        sha = target_sha if i == 0 else secrets.token_hex(32)
        items_json = (
            json.dumps(
                [
                    {
                        "name": "rice",
                        "estimated_amount_g": 100.0,
                        "kcal": 130,
                        "protein_g": 2,
                        "carbs_g": 28,
                        "fat_g": 0,
                        "confidence": 0.9,
                        "matched_food_id": str(uuid.uuid4()),
                        "matched_name_norm": "rice",
                        "match_method": "trigram",
                    }
                ]
            )
            if status == "completed"
            else None
        )
        created = datetime.now(UTC) - timedelta(hours=i)
        await session.execute(
            text(
                """
            INSERT INTO vision_jobs (
                id, user_id, meal_time, status, image_sha256, image_bytes,
                prompt_sha256, detected_items, created_at
            ) VALUES (
                :id, :uid, 'lunch', :status, :sha, 1000,
                :psha, CAST(:items AS jsonb), :created
            )
            """
            ),
            {
                "id": str(uuid.uuid4()),
                "uid": str(user_id),
                "status": status,
                "sha": sha,
                "psha": "promptsha-v1",
                "items": items_json,
                "created": created,
            },
        )
    await session.commit()


@pytest.mark.asyncio
async def test_sha_cache_lookup_uses_partial_index(
    db_session: Any,
    fake_user_id: UUID,
) -> None:
    target_sha = secrets.token_hex(32)
    await _seed_jobs(db_session, fake_user_id, n=100, target_sha=target_sha)

    # Force the planner to consider indexes (small tables otherwise prefer seq scan).
    await db_session.execute(text("SET LOCAL enable_seqscan = OFF"))

    # Run EXPLAIN on the same query SqlVisionJobRepository builds.
    explain_sql = """
        EXPLAIN (FORMAT JSON)
        SELECT detected_items, prompt_sha256
          FROM vision_jobs
         WHERE image_sha256 = :sha
           AND status = 'completed'
           AND created_at >= :cutoff
           AND detected_items IS NOT NULL
         ORDER BY created_at DESC
         LIMIT 1
    """
    cutoff = datetime.now(UTC) - timedelta(days=14)
    plan_row = (
        await db_session.execute(
            text(explain_sql),
            {"sha": target_sha, "cutoff": cutoff},
        )
    ).scalar_one()
    plan_text = json.dumps(plan_row)

    assert (
        "ix_vision_jobs_sha_recent" in plan_text
    ), f"Cache lookup did not use the partial index. Plan: {plan_text}"

    # Verify repo returns the cached row + strips PII.
    repo = SqlVisionJobRepository(db_session)
    out = await repo.find_recent_completed_by_sha(
        image_sha256=target_sha,
        ttl_days=14,
        current_prompt_sha256="promptsha-v1",
    )
    assert out is not None
    items, prompt_sha = out
    assert prompt_sha == "promptsha-v1"
    assert len(items) == 1
    # CRITICAL-2 PII strip enforced.
    assert items[0].matched_food_id is None
    assert items[0].match_method is None
    # But LLM detection survived.
    assert items[0].name == "rice"


@pytest.mark.asyncio
async def test_cache_miss_when_prompt_sha_drifts(
    db_session: Any,
    fake_user_id: UUID,
) -> None:
    """HIGH-1: cache must invalidate when current_prompt_sha256 differs from
    the originally stored prompt_sha256.
    """
    target_sha = secrets.token_hex(32)
    await _seed_jobs(db_session, fake_user_id, n=2, target_sha=target_sha)

    repo = SqlVisionJobRepository(db_session)

    # Old prompt — miss.
    miss = await repo.find_recent_completed_by_sha(
        image_sha256=target_sha,
        ttl_days=14,
        current_prompt_sha256="prompt-v2-different",
    )
    assert miss is None

    # Current prompt matches what was inserted ('promptsha-v1') — hit.
    hit = await repo.find_recent_completed_by_sha(
        image_sha256=target_sha,
        ttl_days=14,
        current_prompt_sha256="promptsha-v1",
    )
    assert hit is not None
