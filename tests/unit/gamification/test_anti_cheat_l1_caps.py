"""ADR-0026 Layer 1 — Redis cap primitives unit tests.

Uses fakeredis to validate atomic INCR + EXPIRE semantics. The cap
helpers must never decrement on read, and the cap-exceeded predicate
must be monotone (once value > cap, every subsequent observation must
also report exceeded).
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.gamification.infrastructure.anti_cheat_caps import (
    FOOD_LOG_PER_SLOT_CAP,
    XP_DAILY_CAP,
    XP_PHOTO_CAP,
    XP_TEXT_CAP,
    XP_WEIGHT_CAP,
    check_and_increment_food_log_slot,
    check_and_increment_xp_daily,
    check_and_mark_sha_used,
    is_xp_cap_exceeded,
)

pytestmark = pytest.mark.anyio


async def test_xp_increment_returns_running_total(fake_redis):
    uid = uuid4()
    today = date(2026, 6, 4)
    v1 = await check_and_increment_xp_daily(fake_redis, uid, today, "text", 50)
    v2 = await check_and_increment_xp_daily(fake_redis, uid, today, "text", 50)
    v3 = await check_and_increment_xp_daily(fake_redis, uid, today, "text", 50)
    assert (v1, v2, v3) == (50, 100, 150)


async def test_xp_increment_zero_returns_current_value(fake_redis):
    uid = uuid4()
    today = date(2026, 6, 4)
    await check_and_increment_xp_daily(fake_redis, uid, today, "text", 30)
    same = await check_and_increment_xp_daily(fake_redis, uid, today, "text", 0)
    assert same == 30


async def test_xp_buckets_are_independent(fake_redis):
    uid = uuid4()
    today = date(2026, 6, 4)
    await check_and_increment_xp_daily(fake_redis, uid, today, "text", 100)
    photo = await check_and_increment_xp_daily(
        fake_redis, uid, today, "photo", 25
    )
    assert photo == 25


async def test_xp_caps_distinguish_buckets():
    # Cap predicate is a pure helper; values >cap return True, equal is OK.
    assert is_xp_cap_exceeded(XP_TEXT_CAP + 1, XP_TEXT_CAP)
    assert not is_xp_cap_exceeded(XP_TEXT_CAP, XP_TEXT_CAP)
    assert not is_xp_cap_exceeded(0, XP_DAILY_CAP)


async def test_xp_text_cap_value():
    assert XP_TEXT_CAP == 150


async def test_xp_photo_cap_value():
    assert XP_PHOTO_CAP == 200


async def test_xp_weight_cap_value():
    assert XP_WEIGHT_CAP == 30


async def test_food_slot_cap_increments(fake_redis):
    uid = uuid4()
    today = date(2026, 6, 4)
    for expected in (1, 2, 3, 4):
        got = await check_and_increment_food_log_slot(
            fake_redis, uid, today, "lunch"
        )
        assert got == expected
    # 4 > cap 3
    assert FOOD_LOG_PER_SLOT_CAP == 3


async def test_food_slot_cap_per_slot_independent(fake_redis):
    uid = uuid4()
    today = date(2026, 6, 4)
    await check_and_increment_food_log_slot(fake_redis, uid, today, "lunch")
    breakfast = await check_and_increment_food_log_slot(
        fake_redis, uid, today, "breakfast"
    )
    assert breakfast == 1


async def test_sha_first_use_true_replay_false(fake_redis):
    uid = uuid4()
    sha = "a" * 64
    first = await check_and_mark_sha_used(fake_redis, uid, sha)
    second = await check_and_mark_sha_used(fake_redis, uid, sha)
    assert first is True
    assert second is False


async def test_sha_per_user_isolated(fake_redis):
    uid_a, uid_b = uuid4(), uuid4()
    sha = "b" * 64
    assert await check_and_mark_sha_used(fake_redis, uid_a, sha) is True
    # Other user sees first-use too.
    assert await check_and_mark_sha_used(fake_redis, uid_b, sha) is True


@settings(max_examples=30, deadline=None)
@given(amounts=st.lists(st.integers(min_value=1, max_value=100), min_size=1, max_size=20))
async def test_cap_counter_monotone_property(amounts):
    """Counter never decreases: each INCR returns a value ≥ previous."""
    import fakeredis.aioredis

    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    uid = uuid4()
    today = date(2026, 6, 4)
    last = 0
    try:
        for amt in amounts:
            v = await check_and_increment_xp_daily(redis, uid, today, "total", amt)
            assert v >= last
            assert v == last + amt
            last = v
        # Reading with amount=0 should NOT change the counter.
        peek = await check_and_increment_xp_daily(redis, uid, today, "total", 0)
        assert peek == last
    finally:
        await redis.aclose()
