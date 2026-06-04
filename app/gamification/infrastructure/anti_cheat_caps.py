"""ADR-0026 Layer 1 — Redis-backed anti-cheat caps.

Pure infrastructure functions: no domain coupling, no SQLAlchemy. Each
helper performs a single atomic Redis primitive (INCR / SET NX) so the
check-and-bump pattern is race-free across worker processes and API
replicas.

Key conventions (all keyed by user_id + UTC date when daily-scoped, so
keys expire naturally and never accumulate):

    xp:cap:<user_id>:total:<YYYY-MM-DD>       — total XP today
    xp:cap:<user_id>:text:<YYYY-MM-DD>        — XP from text logs today
    xp:cap:<user_id>:photo:<YYYY-MM-DD>       — XP from photo logs today
    xp:cap:<user_id>:weight:<YYYY-MM-DD>      — XP from weight logs today
    foodlog:slot:<user_id>:<slot>:<YYYY-MM-DD> — food logs per meal slot today
    sha:used:<user_id>:<sha256>               — same-SHA suppression (24h)

TTL: 48h on daily counters (one day grace beyond the UTC rollover) so
late-arriving events of "yesterday" still see the correct counter.

Caps (ADR-0026 Layer 1 table):
    Total XP/day  500       Text XP/day   150
    Photo XP/day  200       Weight XP/day 30
    Food log per meal slot 3   Same-SHA suppression 24h
"""

from __future__ import annotations

from datetime import date
from typing import Final
from uuid import UUID

from redis.asyncio import Redis

# Caps — single source of truth for L1.
XP_DAILY_CAP: Final[int] = 500
XP_TEXT_CAP: Final[int] = 150
XP_PHOTO_CAP: Final[int] = 200
XP_WEIGHT_CAP: Final[int] = 30
FOOD_LOG_PER_SLOT_CAP: Final[int] = 3

# TTLs (seconds).
_DAILY_TTL_S: Final[int] = 48 * 3600
_SHA_SUPPRESSION_TTL_S: Final[int] = 24 * 3600
_FOOD_SLOT_TTL_S: Final[int] = 48 * 3600


def _xp_key(user_id: UUID, bucket: str, on: date) -> str:
    return f"xp:cap:{user_id}:{bucket}:{on.isoformat()}"


def _slot_key(user_id: UUID, slot: str, on: date) -> str:
    return f"foodlog:slot:{user_id}:{slot}:{on.isoformat()}"


def _sha_key(user_id: UUID, sha256: str) -> str:
    return f"sha:used:{user_id}:{sha256}"


async def check_and_increment_xp_daily(
    redis: Redis,
    user_id: UUID,
    on: date,
    bucket: str,
    amount: int,
) -> int:
    """Atomic INCR + EXPIRE. Returns the post-increment value.

    Caller compares against the relevant cap and rolls back the award
    (or simply no-ops) if exceeded. Uses a pipeline so EXPIRE is set on
    the first increment without an extra round-trip.
    """
    if amount <= 0:
        # Reading the counter without mutating it.
        raw = await redis.get(_xp_key(user_id, bucket, on))
        return int(raw) if raw else 0
    pipe = redis.pipeline()
    key = _xp_key(user_id, bucket, on)
    pipe.incrby(key, amount)
    pipe.expire(key, _DAILY_TTL_S)
    result = await pipe.execute()
    return int(result[0])


def is_xp_cap_exceeded(value: int, cap: int) -> bool:
    """Strict `>` — value equal to cap is still acceptable (we credited
    exactly up to the cap and stopped)."""
    return value > cap


async def check_and_increment_food_log_slot(
    redis: Redis,
    user_id: UUID,
    on: date,
    meal_slot: str,
    amount: int = 1,
) -> int:
    """Atomic INCR for the per-meal-slot food-log counter.

    Returns post-increment value. Caller compares against
    `FOOD_LOG_PER_SLOT_CAP`. TTL 48h so the counter dies naturally.
    """
    pipe = redis.pipeline()
    key = _slot_key(user_id, meal_slot, on)
    pipe.incrby(key, amount)
    pipe.expire(key, _FOOD_SLOT_TTL_S)
    result = await pipe.execute()
    return int(result[0])


async def check_and_mark_sha_used(
    redis: Redis,
    user_id: UUID,
    sha256: str,
    ttl: int = _SHA_SUPPRESSION_TTL_S,
) -> bool:
    """SET NX returns True on first use, False if the SHA was already
    seen for this user within `ttl` seconds.

    Used by the photo-XP path to suppress XP on replays of the same
    image. The vision dedup cache (ADR-0021) is cross-user; this guard
    is the per-user counterpart.
    """
    # SET key 1 NX EX ttl — atomic claim.
    ok = await redis.set(_sha_key(user_id, sha256), "1", nx=True, ex=ttl)
    return bool(ok)
