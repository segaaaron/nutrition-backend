"""Infrastructure — Redis inflight-dedup lock for vision jobs.

Prevents duplicate provider calls when two workers process the same
image SHA concurrently.  All operations are fail-open: a Redis hiccup
degrades to no dedup (both workers call the provider) rather than
blocking a user's photo submission.

Must never be imported by the domain layer.
"""
from __future__ import annotations

import asyncio
from typing import Any

from app.core.cache_keys import CacheKeys
from app.core.logging import get_logger
from app.core.metrics import VISION_CACHE_HITS, VISION_CACHE_MISSES, VISION_INFLIGHT_LOCK_WAITS
from app.vision.domain.entities import DetectedFoodItem
from app.vision.infrastructure.cache_normalizer import normalize_cache_result

log = get_logger("vision.inflight_lock")

_INFLIGHT_LOCK_TTL_S: int = 60   # max provider call duration before lock expires
_INFLIGHT_WAIT_S: int = 30       # waiter polls for this many seconds before fallthrough
_INFLIGHT_KEY_FMT: str = CacheKeys.VISION_INFLIGHT


async def acquire_lock(image_sha: str, redis: Any) -> bool:
    """SET NX EX the inflight key.  Returns True if lock acquired, False if held."""
    key = _INFLIGHT_KEY_FMT.format(sha=image_sha)
    try:
        return bool(await redis.set(key, "1", nx=True, ex=_INFLIGHT_LOCK_TTL_S))
    except Exception as exc:  # noqa: BLE001 — OK4: fail-open; degrade to non-locked path
        log.warning("vision.inflight.acquire_failed", err=str(exc))
        return True  # treat as acquired so this worker proceeds


async def release_lock(image_sha: str, redis: Any) -> None:
    """DELETE the inflight key.  Best-effort: TTL bounds worst-case stale lock."""
    key = _INFLIGHT_KEY_FMT.format(sha=image_sha)
    try:
        await redis.delete(key)
    except Exception as exc:  # noqa: BLE001 — OK4: TTL-bounded stale lock; logged only
        log.debug("vision.inflight.release_failed", err=str(exc), key=key)


async def poll_until_cached(
    image_sha: str,
    *,
    repo: Any,
    settings: Any,
    current_prompt_sha: str,
    job_meta: Any,
) -> tuple[list[DetectedFoodItem], str] | None:
    """Poll the SHA cache while another worker holds the inflight lock.

    Returns normalised ``(items, prompt_sha)`` on a cache hit, or None
    after ``_INFLIGHT_WAIT_S`` seconds (caller falls through to a direct
    provider call — lock holder likely crashed).
    """
    for _ in range(_INFLIGHT_WAIT_S):
        await asyncio.sleep(1)
        try:
            raw = await repo.find_recent_completed_by_sha(
                image_sha256=image_sha,
                ttl_days=settings.vision_cache_ttl_days,
                current_prompt_sha256=current_prompt_sha,
            )
        except Exception as exc:  # noqa: BLE001 — OK4: DB hiccup during poll; skip tick, keep waiting
            log.debug("vision.inflight.poll_db_failed", err=str(exc))
            continue
        result = normalize_cache_result(raw)
        if result is not None:
            VISION_INFLIGHT_LOCK_WAITS.labels(outcome="hit").inc()
            VISION_CACHE_HITS.inc()
            items, sha = result
            return items, sha or (getattr(job_meta, "prompt_sha256", None) or "")

    VISION_INFLIGHT_LOCK_WAITS.labels(outcome="timeout").inc()
    VISION_CACHE_MISSES.inc()
    return None
