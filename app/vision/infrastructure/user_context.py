"""Infrastructure — user profile + per-user portion calibration loader.

Both loaders are best-effort: they return safe defaults on any infra error
so a Redis/DB hiccup never blocks a photo submission.

Must never be imported by the domain layer.
"""
from __future__ import annotations

import json
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache_keys import CacheKeys
from app.core.logging import get_logger
from app.core.redis import get_redis

log = get_logger("vision.user_context")

_PORTION_CAL_TTL = 3600  # 1 hour


async def load_user_profile(
    *, user_id: UUID, session: AsyncSession
) -> dict[str, object] | None:
    """Fetch age / sex / weight_kg / country for LLM portion-calibration hint (F5.2).

    Returns None when the profile row is missing or on any DB error.
    """
    try:
        row = (
            await session.execute(
                text(
                    "SELECT age, sex, weight_kg, country"
                    " FROM user_profiles"
                    " WHERE user_id = :uid"
                ),
                {"uid": str(user_id)},
            )
        ).first()
        if not row:
            return None
        return {"age": row[0], "sex": row[1], "weight_kg": row[2], "country": row[3]}
    except Exception as exc:  # noqa: BLE001 — OK4: profile is a best-effort LLM hint
        log.debug("vision.user_profile.failed", err=str(exc)[:120])
        return None


async def load_portion_calibration(
    *, user_id: UUID, session: AsyncSession
) -> dict[str, float]:
    """Return {food_group: correction_ratio} for this user (F3.2).

    Cache hierarchy:
      1. Redis key ``nova:portion_cal:{user_id}`` (TTL 1 h).
      2. ``user_portion_calibration`` table (sample_count ≥ 2).

    Returns empty dict on any error — caller assumes identity ratio.
    """
    redis_key = CacheKeys.PORTION_CAL.format(user_id=user_id)

    try:
        raw = await get_redis().get(redis_key)
        if raw:
            return cast("dict[str, float]", json.loads(raw))
    except Exception:  # noqa: BLE001 — OK4: cache miss → fall through to DB
        pass

    try:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT food_group, correction_ratio
                      FROM user_portion_calibration
                     WHERE user_id = :uid
                       AND sample_count >= 2
                    """
                ),
                {"uid": str(user_id)},
            )
        ).all()
        result: dict[str, float] = {r[0]: float(r[1]) for r in rows}

        if result:
            try:
                await get_redis().setex(redis_key, _PORTION_CAL_TTL, json.dumps(result))
            except Exception:  # noqa: BLE001 — OK4: cache write is best-effort
                pass

        return result

    except Exception as exc:  # noqa: BLE001 — OK4: calibration best-effort; identity ratio assumed
        log.debug("vision.portion_calibration.failed", err=str(exc)[:120])
        return {}


async def load_recent_portion_anchors(
    *, user_id: UUID, session: AsyncSession
) -> list[str]:
    """Fetch up to 6 user-corrected portion sizes as LLM prompt anchors (F5.3).

    Returns list of "food_name Xg" strings ordered by correction frequency.
    Best-effort: returns [] on any infra error.
    """
    try:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT detected_name_norm, corrected_amount_g
                      FROM vision_user_corrections
                     WHERE user_id = :uid
                       AND corrected_amount_g IS NOT NULL
                     ORDER BY occurrences DESC
                     LIMIT 6
                    """
                ),
                {"uid": str(user_id)},
            )
        ).all()
        return [f"{r[0]} {int(r[1])}g" for r in rows if r[0] and r[1]]
    except Exception as exc:  # noqa: BLE001 — OK4: portion anchors are best-effort LLM hints
        log.debug("vision.portion_anchors.failed", err=str(exc)[:120])
        return []
