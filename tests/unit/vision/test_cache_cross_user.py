"""Unit — CRITICAL-2 fix: SHA dedup cache must NOT leak per-user matcher
artifacts (matched_food_id, matched_name_norm, match_method) across users.

Two checks:
  1. `_strip_personal_fields` removes all three keys from cached dicts.
  2. A cache-hit run with user B re-invokes FoodMatcher with B's user_id
     (the cached A-matched food_id is wiped, and B's own matcher result
     ends up on the items).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.vision.application.process_vision_job import ProcessVisionJob
from app.vision.domain.entities import DetectedFoodItem, VisionJob
from app.vision.infrastructure.repositories import _strip_personal_fields


def test_strip_personal_fields_removes_pii() -> None:
    cached_raw = [
        {
            "name": "avena",
            "estimated_amount_g": 60.0,
            "kcal": 230,
            "protein_g": 7,
            "carbs_g": 40,
            "fat_g": 4,
            "confidence": 0.9,
            "matched_food_id": "11111111-1111-1111-1111-111111111111",
            "matched_name_norm": "AVENA-USER-A",
            "match_method": "personal_cache",
        }
    ]
    out = _strip_personal_fields(cached_raw)
    assert "matched_food_id" not in out[0]
    assert "matched_name_norm" not in out[0]
    assert "match_method" not in out[0]
    # LLM detection fields preserved.
    assert out[0]["name"] == "avena"
    assert out[0]["kcal"] == 230


@pytest.mark.asyncio
async def test_cache_hit_rematches_for_new_user() -> None:
    """User A originally matched 'avena' to FOOD_A via personal_cache.
    When User B's job hits the same SHA, the cached row arrives PII-stripped
    and matcher fires fresh — landing User B's own catalog match (FOOD_B)."""
    job_id = uuid4()
    user_b = uuid4()
    sha = "c" * 64

    repo = MagicMock()
    repo.mark_running = AsyncMock()
    repo.mark_completed = AsyncMock()
    repo.mark_failed = AsyncMock()
    repo.get = AsyncMock(
        return_value=VisionJob(
            id=job_id,
            user_id=user_b,
            image_sha256=sha,
            status="running",
            created_at=datetime.now(UTC),
        )
    )
    # Simulate the repository correctly stripping PII before returning.
    stripped_item = DetectedFoodItem(
        name="avena",
        estimated_amount_g=Decimal("60"),
        kcal=230,
        protein_g=7,
        carbs_g=40,
        fat_g=4,
        confidence=0.9,
        matched_food_id=None,
        matched_name_norm=None,
        match_method=None,
    )
    repo.find_recent_completed_by_sha = AsyncMock(
        return_value=([stripped_item], "promptsha-original")
    )

    provider = MagicMock()
    provider.recognise = AsyncMock()  # must NOT be called

    food_b_id = uuid4()
    matcher = MagicMock()
    matcher.match = AsyncMock(return_value=(food_b_id, "AVENA-USER-B", "trigram", None))

    session = MagicMock()
    _exec_result = MagicMock()
    _exec_result.all.return_value = []
    session.execute = AsyncMock(return_value=_exec_result)
    notifier = MagicMock()
    notifier.notify = AsyncMock()
    bus = MagicMock()
    bus.publish = AsyncMock()

    uc = ProcessVisionJob(
        repo=repo,
        provider=provider,
        matcher=matcher,
        notifier=notifier,
        bus=bus,
        session=session,
    )
    await uc(
        job_id=job_id,
        user_id=user_b,
        meal_time="lunch",
        image_bytes=b"ignored",
        mime="image/jpeg",
        locale="es",
        region="latam",
    )

    # Matcher MUST be invoked for user_b with the stripped name.
    matcher.match.assert_awaited_once()
    kwargs = matcher.match.await_args.kwargs
    assert kwargs["user_id"] == user_b
    assert kwargs["name"] == "avena"
    provider.recognise.assert_not_called()

    # The item that lands in mark_completed must carry user_b's match,
    # NOT user_a's leaked food_id.
    completed_items = repo.mark_completed.await_args.kwargs["items"]
    assert completed_items[0].matched_food_id == food_b_id
    assert completed_items[0].matched_name_norm == "AVENA-USER-B"
