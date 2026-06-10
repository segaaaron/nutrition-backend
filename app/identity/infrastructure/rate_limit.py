"""Redis sliding-window rate limiter. Per-endpoint, per-key.

Algorithm: ZSET keyed by `rl:{scope}:{identifier}`; each request adds one
timestamp; window-old entries are pruned; if ZCARD > limit we 429.
"""

from __future__ import annotations

import time

from redis.exceptions import RedisError

from app.core.errors import RateLimited
from app.core.logging import get_logger
from app.core.redis import get_redis

log = get_logger("identity.rate_limit")


async def rate_limit(
    *,
    scope: str,
    identifier: str,
    limit_per_min: int,
    window_s: int = 60,
) -> None:
    """Raises RateLimited on overflow; no return value otherwise.

    ``window_s`` overrides the default 60-second sliding window. Use 3600
    for hourly buckets (e.g. OTP send rate-limit per email per hour).
    """
    now_ms = int(time.time() * 1000)
    window_ms = window_s * 1000
    key = f"rl:{scope}:{identifier}"
    # QA: Redis acquisition itself can fail (pool exhausted, DNS, factory
    # raises). The full path — client construction → pipeline build → execute
    # — must fail open. Otherwise a Redis outage would convert into a hard
    # HTTP 500 across every auth endpoint, which is the failure mode the
    # rate-limiter is meant to *prevent*. We catch RedisError plus any
    # generic Exception from the factory (covers ConnectionPool errors and
    # tests that patch ``get_redis`` to raise).
    try:
        redis = get_redis()
        pipe = redis.pipeline()
        pipe.zremrangebyscore(key, 0, now_ms - window_ms)
        pipe.zadd(key, {f"{now_ms}-{id(object())}": now_ms})
        pipe.zcard(key)
        pipe.pexpire(key, window_ms)
        _, _, count, _ = await pipe.execute()
    except RedisError as exc:
        log.warning("rate_limit.redis_down", err=str(exc))
        return
    except Exception as exc:  # noqa: BLE001 — fail-open on any infra surprise
        log.warning("rate_limit.infra_error", err_type=type(exc).__name__)
        return
    if int(count) > limit_per_min:
        raise RateLimited(f"rate_limited:{scope}", limit=limit_per_min, window_s=window_s)
