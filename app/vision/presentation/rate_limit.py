"""Per-user daily photo upload rate limit (Capa 4 of the vision cost
cascade).

Extracted into its own module so unit tests don't pay the cost of importing
the FastAPI router (which transitively requires libvips for the photo
compressor). Lives in the presentation layer because the only consumer is
the HTTP handler.

Key format (spec):
    photo_uploads:{user_id}:{YYYY-MM-DD}

Limit and retry-after policy:
- Settings-driven (``vision_photo_uploads_per_day``). Default 10/day.
- On excess, raises ``RateLimited`` with ``retry_after`` set to seconds
  until midnight UTC (honest reset time).
- 10/day: breakfast + lunch + dinner + snack + retries — covers 99% of users.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from redis.exceptions import RedisError

from app.core.config import get_settings
from app.core.errors import DomainError, RateLimited
from app.core.logging import get_logger
from app.core.redis import get_redis

log = get_logger("vision.rate_limit")


class ServiceUnavailable(DomainError):
    """Fail-closed when a critical infra dep (Redis) is unreachable.

    MEDIUM-2: previously the rate limiter swallowed Redis errors and the
    request proceeded uncounted (fail-open) — abuse risk. Now we return
    503 Retry-After: 30 so the client backs off.
    """

    http_status = 503
    type_slug = "service-unavailable"
    title = "Service temporarily unavailable"


async def check_photo_upload_rate_limit(user_id: UUID) -> None:
    s = get_settings()
    limit = s.vision_photo_uploads_per_day
    now = datetime.now(UTC)
    day_bucket = now.strftime("%Y-%m-%d")
    key = f"photo_uploads:{user_id}:{day_bucket}"
    r = get_redis()
    pipe = r.pipeline()
    pipe.incr(key)
    pipe.expire(key, 86_500)  # 24h + 100s buffer
    try:
        n, _ = await pipe.execute()
    except RedisError as exc:
        log.warning("rate_limit.redis_down", err=str(exc))
        raise ServiceUnavailable(
            "rate_limit_unavailable",
            retry_after=30,
        ) from exc
    if int(n) > limit:
        midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        retry_after = max(1, int((midnight - now).total_seconds()))
        raise RateLimited(
            "rate_limit_exceeded",
            retry_after_s=retry_after,
            error="rate_limit_exceeded",
            retry_after=retry_after,
        )
