"""Unit — SqlVisionJobRepository pure helpers + boundary behaviour.

Hits real SQL behaviour via integration tests; here we cover:
- pure JSONB serialisation/deserialisation roundtrip
- PII strip removes matched_food_id / matched_name_norm / match_method
- save / mark_running / mark_completed / mark_failed each call the
  session exactly once with the expected high-level intent
- find_recent_completed_by_sha returns None on no row, returns
  (items, prompt_sha) on hit, strips PII before returning
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.vision.domain.entities import DetectedFoodItem, VisionJob
from app.vision.infrastructure.repositories import (
    SqlVisionJobRepository,
    _items_from_jsonb,
    _items_to_jsonb,
    _strip_personal_fields,
)


def _item(name="oat", matched=True):
    return DetectedFoodItem(
        name=name,
        estimated_amount_g=Decimal("60"),
        kcal=230,
        protein_g=7,
        carbs_g=40,
        fat_g=4,
        confidence=0.9,
        matched_food_id=uuid4() if matched else None,
        matched_name_norm=name if matched else None,
        match_method="trigram" if matched else None,
    )


def test_items_to_jsonb_serialises_decimal_to_float():
    rows = _items_to_jsonb([_item()])
    assert isinstance(rows[0]["estimated_amount_g"], float)
    assert rows[0]["estimated_amount_g"] == 60.0


def test_items_to_jsonb_stringifies_matched_food_uuid():
    item = _item()
    rows = _items_to_jsonb([item])
    assert rows[0]["matched_food_id"] == str(item.matched_food_id)


def test_items_to_jsonb_none_when_unmatched():
    rows = _items_to_jsonb([_item(matched=False)])
    assert rows[0]["matched_food_id"] is None
    assert rows[0]["matched_name_norm"] is None
    assert rows[0]["match_method"] is None


def test_jsonb_roundtrip_preserves_values():
    original = [_item("rice"), _item("beans", matched=False)]
    rows = _items_to_jsonb(original)
    restored = _items_from_jsonb(rows)
    assert len(restored) == 2
    assert restored[0].name == "rice"
    assert restored[0].kcal == 230
    assert restored[0].matched_food_id == original[0].matched_food_id
    assert restored[1].matched_food_id is None


# BE-5 — bounding box serialization.
def test_bbox_roundtrips_through_jsonb():
    item = _item()
    object.__setattr__(item, "bbox", (0.1, 0.2, 0.3, 0.4))
    rows = _items_to_jsonb([item])
    assert rows[0]["bbox"] == [0.1, 0.2, 0.3, 0.4]
    restored = _items_from_jsonb(rows)
    assert restored[0].bbox == (0.1, 0.2, 0.3, 0.4)


def test_bbox_none_serialises_and_restores_as_none():
    rows = _items_to_jsonb([_item()])  # default bbox=None
    assert rows[0]["bbox"] is None
    assert _items_from_jsonb(rows)[0].bbox is None


def test_bbox_malformed_cache_row_restores_as_none():
    # Defensive: a corrupt cache row (wrong length / non-list) must never
    # crash the DTO mapping — it degrades to None.
    base = _items_to_jsonb([_item()])[0]
    for bad in ([0.1, 0.2, 0.3], "0.1,0.2", {"x": 0.1}, [0.1, 0.2, 0.3, 0.4, 0.5]):
        row = {**base, "bbox": bad}
        assert _items_from_jsonb([row])[0].bbox is None


def test_items_from_jsonb_returns_empty_for_none():
    assert _items_from_jsonb(None) == []


def test_items_from_jsonb_returns_empty_for_empty_list():
    assert _items_from_jsonb([]) == []


def test_jsonb_roundtrip_preserves_food_group():
    item = _item("rice")
    item.food_group = "grain"
    restored = _items_from_jsonb(_items_to_jsonb([item]))
    assert restored[0].food_group == "grain"


def test_items_from_jsonb_legacy_rows_without_food_group():
    rows = _items_to_jsonb([_item("oat")])
    for r in rows:
        r.pop("food_group", None)  # simulate pre-bump cached row
    restored = _items_from_jsonb(rows)
    assert restored[0].food_group is None


def test_items_from_jsonb_coerces_out_of_vocab_food_group_to_other():
    rows = _items_to_jsonb([_item("oat")])
    rows[0]["food_group"] = "hallucinated_future_group"
    restored = _items_from_jsonb(rows)
    assert restored[0].food_group == "other"


def test_strip_personal_fields_preserves_food_group():
    item = _item()
    item.food_group = "vegetable"
    cleaned = _strip_personal_fields(_items_to_jsonb([item]))
    # food_group is image-bound (not per-user) — MUST survive the
    # cross-user SHA cache strip.
    assert cleaned[0]["food_group"] == "vegetable"


def test_strip_personal_fields_removes_matcher_artifacts():
    rows = _items_to_jsonb([_item()])
    cleaned = _strip_personal_fields(rows)

    assert "matched_food_id" not in cleaned[0]
    assert "matched_name_norm" not in cleaned[0]
    assert "match_method" not in cleaned[0]
    # Non-matcher fields preserved.
    assert cleaned[0]["name"] == "oat"
    assert cleaned[0]["kcal"] == 230


def test_strip_personal_fields_does_not_mutate_input():
    rows = _items_to_jsonb([_item()])
    snapshot = [dict(r) for r in rows]
    _strip_personal_fields(rows)
    assert rows == snapshot


# --- session-boundary tests ---------------------------------------------------


def _async_session():
    s = MagicMock()
    s.add = MagicMock()
    s.flush = AsyncMock()
    s.execute = AsyncMock()
    return s


@pytest.mark.asyncio
async def test_save_adds_model_and_flushes():
    """save() persists via session.add + flush. Full ORM mapping is exercised
    by tests/integration/vision/test_save_get_roundtrip.py against real PG."""
    session = _async_session()
    # Replace VisionJobModel constructor with a stub to avoid triggering the
    # cross-context mapper configure (RecipeModel relationships need PG).
    from unittest.mock import patch

    repo = SqlVisionJobRepository(session)
    job = VisionJob(
        id=uuid4(),
        user_id=uuid4(),
        image_sha256="a" * 64,
        image_bytes=12345,
        status="queued",
        created_at=datetime.now(UTC),
    )

    with patch(
        "app.vision.infrastructure.repositories.VisionJobModel",
        side_effect=lambda **kw: kw,  # returns the kwargs dict instead of ORM instance
    ):
        await repo.save(job)

    session.add.assert_called_once()
    session.flush.assert_awaited_once()
    added = session.add.call_args[0][0]
    assert added["id"] == job.id
    assert added["image_sha256"] == job.image_sha256


@pytest.mark.asyncio
async def test_save_uses_current_time_when_created_at_missing():
    from unittest.mock import patch

    session = _async_session()
    repo = SqlVisionJobRepository(session)
    job = VisionJob(
        id=uuid4(),
        user_id=uuid4(),
        image_sha256="b" * 64,
        image_bytes=1,
        status="queued",
        created_at=None,
    )

    with patch(
        "app.vision.infrastructure.repositories.VisionJobModel",
        side_effect=lambda **kw: kw,
    ):
        await repo.save(job)

    added = session.add.call_args[0][0]
    assert added["created_at"] is not None


@pytest.mark.asyncio
async def test_mark_running_executes_update():
    session = _async_session()
    repo = SqlVisionJobRepository(session)
    await repo.mark_running(uuid4())
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_mark_completed_executes_update():
    session = _async_session()
    repo = SqlVisionJobRepository(session)
    await repo.mark_completed(uuid4(), items=[_item()])
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_mark_completed_persists_prompt_sha256():
    """The sha dedup cache is dead unless completion writes `prompt_sha256`.

    Regression for the PROD incident found 2026-07-17: all 8 vision_jobs rows
    had `prompt_sha256 = NULL`, because `mark_completed` never wrote the column.
    `find_recent_completed_by_sha` filters on `prompt_sha256 == current` (the
    HIGH-1 prompt-invalidation guard), and in SQL `NULL = <anything>` is never
    true — so every lookup returned 0 rows and the model re-ran on every upload.
    Same image, same sha256, 5 uploads → 10/10/10/10/9 items, i.e. the user saw
    different calories for one photo.
    """
    session = _async_session()
    repo = SqlVisionJobRepository(session)

    await repo.mark_completed(uuid4(), items=[_item()], prompt_sha256="deadbeef")

    stmt = session.execute.await_args.args[0]
    values = stmt.compile().params
    assert "deadbeef" in values.values(), (
        f"prompt_sha256 not written on completion; UPDATE params were {values}"
    )


@pytest.mark.asyncio
async def test_mark_completed_skips_empty_prompt_sha256():
    """An empty sha must not overwrite the column — it is as dead as NULL.

    The cache-hit path yields `cached_sha or ... or ""`, so a legacy row stored
    before `prompt_sha256` was persisted hands back "". Writing that would keep
    the row permanently un-cacheable, since "" never equals a real prompt sha.
    """
    session = _async_session()
    repo = SqlVisionJobRepository(session)

    await repo.mark_completed(uuid4(), items=[_item()], prompt_sha256="")

    stmt = session.execute.await_args.args[0]
    values = stmt.compile().params
    assert "" not in values.values(), f"empty prompt_sha256 was written: {values}"


@pytest.mark.asyncio
async def test_mark_failed_caps_detail_at_500_chars():
    session = _async_session()
    repo = SqlVisionJobRepository(session)

    long_detail = "x" * 1000
    await repo.mark_failed(uuid4(), error_code="ProviderError", detail=long_detail)

    # SQLAlchemy core update() args — inspect via .values
    call_args = session.execute.call_args
    update_stmt = call_args[0][0]
    bound = update_stmt.compile().params
    # The detail param is one of the bind values; verify length capped.
    detail_values = [v for v in bound.values() if isinstance(v, str) and v.startswith("x")]
    assert detail_values
    assert all(len(v) <= 500 for v in detail_values)


@pytest.mark.asyncio
async def test_get_returns_none_when_no_row():
    session = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=None)
    session.execute = AsyncMock(return_value=result)

    repo = SqlVisionJobRepository(session)
    assert await repo.get(uuid4()) is None


@pytest.mark.asyncio
async def test_get_maps_model_to_entity_with_items():
    job_id = uuid4()
    user_id = uuid4()
    items_raw = _items_to_jsonb([_item("rice")])

    fake_model = MagicMock()
    fake_model.id = job_id
    fake_model.user_id = user_id
    fake_model.meal_time = "lunch"
    fake_model.status = "completed"
    fake_model.image_sha256 = "f" * 64
    fake_model.image_bytes = 999
    fake_model.idempotency_key = "idem-1"
    fake_model.prompt_sha256 = "prompt-1"
    fake_model.detected_items = items_raw
    fake_model.error_code = None
    fake_model.error_detail = None
    fake_model.created_at = datetime.now(UTC)
    fake_model.started_at = None
    fake_model.completed_at = datetime.now(UTC)

    session = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=fake_model)
    session.execute = AsyncMock(return_value=result)

    repo = SqlVisionJobRepository(session)
    job = await repo.get(job_id)

    assert job is not None
    assert job.id == job_id
    assert job.status == "completed"
    assert len(job.detected_items) == 1
    assert job.detected_items[0].name == "rice"


@pytest.mark.asyncio
async def test_find_recent_completed_returns_none_on_miss():
    session = MagicMock()
    result = MagicMock()
    result.first = MagicMock(return_value=None)
    session.execute = AsyncMock(return_value=result)

    repo = SqlVisionJobRepository(session)
    out = await repo.find_recent_completed_by_sha(
        image_sha256="x" * 64,
        ttl_days=14,
    )
    assert out is None


@pytest.mark.asyncio
async def test_find_recent_completed_strips_personal_fields():
    items_with_pii = _items_to_jsonb([_item("rice")])
    assert items_with_pii[0]["matched_food_id"] is not None  # sanity

    session = MagicMock()
    result = MagicMock()
    result.first = MagicMock(return_value=(items_with_pii, "promptsha-1"))
    session.execute = AsyncMock(return_value=result)

    repo = SqlVisionJobRepository(session)
    out = await repo.find_recent_completed_by_sha(
        image_sha256="x" * 64,
        ttl_days=14,
    )

    assert out is not None
    items, prompt_sha = out
    assert prompt_sha == "promptsha-1"
    assert len(items) == 1
    # PII strip: re-hydrated entity has matched_food_id = None.
    assert items[0].matched_food_id is None
    assert items[0].match_method is None
    # But the LLM-detected name + macros are preserved.
    assert items[0].name == "rice"
    assert items[0].kcal == 230


@pytest.mark.asyncio
async def test_find_recent_completed_returns_none_when_raw_items_null():
    session = MagicMock()
    result = MagicMock()
    result.first = MagicMock(return_value=(None, "promptsha-1"))
    session.execute = AsyncMock(return_value=result)

    repo = SqlVisionJobRepository(session)
    out = await repo.find_recent_completed_by_sha(
        image_sha256="x" * 64,
        ttl_days=14,
    )
    assert out is None
