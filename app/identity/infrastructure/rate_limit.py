"""Redis sliding-window rate limiter. Per-endpoint, per-key.

Algorithm: ZSET keyed by `rl:{scope}:{identifier}`; each request adds one
timestamp; window-old entries are pruned; if ZCARD > limit we 429.
"""
from __future__ import annotations

import time

from app.core.errors import RateLimited
from app.core.redis import get_redis


async def rate_limit(
    *,
    scope: str,
    identifier: str,
    limit_per_min: int,
) -> None:
    """Raises RateLimited on overflow; no return value otherwise."""
    now_ms = int(time.time() * 1000)
    window_ms = 60_000
    key = f"rl:{scope}:{identifier}"
    redis = get_redis()
    pipe = redis.pipeline()
    pipe.zremrangebyscore(key, 0, now_ms - window_ms)
    pipe.zadd(key, {f"{now_ms}-{id(object())}": now_ms})
    pipe.zcard(key)
    pipe.pexpire(key, window_ms)
    _, _, count, _ = await pipe.execute()
    if int(count) > limit_per_min:
        raise RateLimited(f"rate_limited:{scope}", limit=limit_per_min, window_s=60)
