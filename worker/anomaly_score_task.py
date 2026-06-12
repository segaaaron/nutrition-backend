"""ADR-0026 L2 anomaly score — nightly Arq cron.

For every user active in the last 7 days (any food_log, weight_log or
vision_job in the window) compute six pure signals (each 0..100, higher
is worse), combine with the canonical weights below, and act on the
final aggregate score::

    score >= 70  → INSERT gamification_shadow_ban (idempotent ON CONFLICT)
    40 <= score < 70 → structured-log warning for owner review
    score < 40   → structured-log info (debug visibility only)

Weighted signals (sum to 1.0)::

    log_timing_entropy            0.20
    phash_duplicate_clustering    0.25
    macro_impossibility           0.20
    weight_intake_mismatch        0.15
    social_density_ip             0.10
    account_age_vs_rank           0.10

When a signal returns ``None`` (insufficient data, missing backing
table) its weight is *redistributed proportionally* across the available
signals so the threshold semantics remain comparable across users.

Schedule: cron daily 02:00 Lima (= 07:00 UTC, registered with
``timezone="America/Lima"`` in ``worker/main.py``).

Privacy: user_id never appears in logs. We hash with SHA-256 and
truncate to 16 hex chars (= 64 bits collision resistance, sufficient for
debugging at NOVA's scale).
"""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import session_scope
from app.core.logging import get_logger
from worker.anomaly_signals import (
    account_age,
    log_timing,
    macro_impossibility,
    phash_clustering,
    social_density,
    weight_intake,
)

logger = get_logger(__name__)

WINDOW_DAYS = 7
BAN_THRESHOLD = 70.0
REVIEW_THRESHOLD = 40.0

# Canonical weights (sum to 1.0). Order matters only for logging keys.
SIGNAL_WEIGHTS: dict[str, float] = {
    "log_timing_entropy": 0.20,
    "phash_duplicate_clustering": 0.25,
    "macro_impossibility": 0.20,
    "weight_intake_mismatch": 0.15,
    "social_density_ip": 0.10,
    "account_age_vs_rank": 0.10,
}

# Each entry maps the canonical signal name to the async compute callable.
_SIGNAL_FNS = {
    "log_timing_entropy": log_timing.compute,
    "phash_duplicate_clustering": phash_clustering.compute,
    "macro_impossibility": macro_impossibility.compute,
    "weight_intake_mismatch": weight_intake.compute,
    "social_density_ip": social_density.compute,
    "account_age_vs_rank": account_age.compute,
}

_SQL_ACTIVE_USERS = text(
    """
    SELECT DISTINCT user_id FROM (
        SELECT user_id FROM food_logs
         WHERE created_at >= now() - make_interval(days => :days)
        UNION
        SELECT user_id FROM weight_logs
         WHERE time >= now() - make_interval(days => :days)
        UNION
        SELECT user_id FROM vision_jobs
         WHERE created_at >= now() - make_interval(days => :days)
    ) AS active
    """
)

_SQL_INSERT_SHADOW_BAN = text(
    """
    INSERT INTO gamification_shadow_ban (user_id, banned_at, reason, score)
    VALUES (:uid, now(), :reason, :score)
    ON CONFLICT (user_id) DO NOTHING
    """
)


def _hash_uid(user_id: UUID) -> str:
    """SHA-256(uid).hexdigest()[:16] — never log raw uid."""
    return hashlib.sha256(str(user_id).encode("utf-8")).hexdigest()[:16]


def aggregate_score(signals: dict[str, float | None]) -> tuple[float, list[str]]:
    """Weighted mean over *available* signals, with weight redistribution.

    Returns ``(score_0_100, available_signal_names)``. If every signal is
    ``None`` the score is ``0.0`` (benign) and the available list is empty
    — the caller should log this as a no-data case.
    """
    available = {
        name: float(value)
        for name, value in signals.items()
        if value is not None
    }
    if not available:
        return 0.0, []

    total_weight = sum(SIGNAL_WEIGHTS[name] for name in available)
    if total_weight <= 0.0:
        return 0.0, sorted(available.keys())

    weighted_sum = 0.0
    for name, value in available.items():
        clipped = max(0.0, min(100.0, value))
        weighted_sum += clipped * (SIGNAL_WEIGHTS[name] / total_weight)
    score = max(0.0, min(100.0, weighted_sum))
    return score, sorted(available.keys())


async def _score_one_user(
    session: AsyncSession, user_id: UUID
) -> tuple[float, dict[str, float | None], list[str]]:
    signals: dict[str, float | None] = {}
    for name, fn in _SIGNAL_FNS.items():
        signals[name] = await fn(session, user_id, WINDOW_DAYS)
    score, available = aggregate_score(signals)
    return score, signals, available


async def _apply_action(
    session: AsyncSession,
    user_id: UUID,
    score: float,
    signals: dict[str, float | None],
    available: list[str],
) -> str:
    """Returns the action label: ``banned`` | ``flagged`` | ``ok`` | ``no_data``."""
    uid_hash = _hash_uid(user_id)
    signal_snapshot = {
        k: (round(v, 2) if v is not None else None) for k, v in signals.items()
    }

    if not available:
        logger.info(
            "anomaly.no_data",
            user_id_hash=uid_hash,
            signals=signal_snapshot,
        )
        return "no_data"

    if score >= BAN_THRESHOLD:
        await session.execute(
            _SQL_INSERT_SHADOW_BAN,
            {
                "uid": str(user_id),
                "reason": f"anomaly_score>={int(BAN_THRESHOLD)}",
                "score": int(round(score)),
            },
        )
        logger.warning(
            "anomaly.banned",
            user_id_hash=uid_hash,
            score=round(score, 2),
            signals=signal_snapshot,
            available_signals=available,
        )
        return "banned"

    if score >= REVIEW_THRESHOLD:
        logger.warning(
            "anomaly.flagged_review",
            user_id_hash=uid_hash,
            score=round(score, 2),
            signals=signal_snapshot,
            available_signals=available,
        )
        return "flagged"

    logger.info(
        "anomaly.scored",
        user_id_hash=uid_hash,
        score=round(score, 2),
        signals=signal_snapshot,
        available_signals=available,
    )
    return "ok"


async def anomaly_score_task(ctx: dict[str, Any]) -> dict[str, int]:  # noqa: ARG001
    """Score active users + ban if >=70 + flag if 40-69.

    Runs nightly 02:00 Lima. Returns aggregate counts for observability.
    """
    stats = {"scored": 0, "banned": 0, "flagged": 0, "ok": 0, "no_data": 0}

    async with session_scope() as session:
        rows = (
            await session.execute(_SQL_ACTIVE_USERS, {"days": WINDOW_DAYS})
        ).all()
        user_ids: list[UUID] = [UUID(str(r[0])) for r in rows]

        for uid in user_ids:
            score, signals, available = await _score_one_user(session, uid)
            action = await _apply_action(session, uid, score, signals, available)
            stats["scored"] += 1
            stats[action] = stats.get(action, 0) + 1

        await session.commit()

    logger.info(
        "anomaly.cycle_complete",
        scored=stats["scored"],
        banned=stats["banned"],
        flagged=stats["flagged"],
        ok=stats["ok"],
        no_data=stats["no_data"],
        window_days=WINDOW_DAYS,
    )
    return stats
