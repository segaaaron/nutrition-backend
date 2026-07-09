"""Centralised Redis cache key patterns.

All Redis key strings in the application live here so they are easy to
audit and impossible to silently duplicate or diverge.

Usage::

    from app.core.cache_keys import CacheKeys
    key = CacheKeys.LOCALE_USER.format(user_id=uid)
"""
from __future__ import annotations


class CacheKeys:
    # i18n locale per authenticated user. TTL: 1 h.
    LOCALE_USER = "locale:user:{user_id}"

    # Per-user food-group portion calibration ratios. TTL: 1 h.
    PORTION_CAL = "nova:portion_cal:{user_id}"

    # Feature-flag: leaderboard toggle. TTL: 60 s.
    FF_LEADERBOARD = "ff:leaderboard"

    # Plan-generation rate-limit counter. TTL: 3600 s (rolling window).
    PLAN_GEN_RL = "plan_gen:{user_id}"

    # Inflight dedup lock for vision provider calls. TTL: 60 s.
    VISION_INFLIGHT = "nova:vision:inflight:{sha}"
