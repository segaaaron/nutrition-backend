"""Arq cron — ADR-0026 retention policy for leaderboard anti-cheat tables.

Three append-only / state tables grow without bound unless purged:

  - `leaderboard_audit`              every XP award (~10 rows/user/day).
  - `profile_region_change_audit`    region changes (rare, but unbounded).
  - `gamification_shadow_ban`        rows with `lifted_at` set are
                                      historical and may also be purged.

Retention horizon: 180 days. Beyond that the data is no longer useful
for the owner-side abuse review (ADR-0026 §"Owner reviews weekly") and
GDPR/LGPD minimisation argues for deletion. Hard deletes are safe —
all rows are append-only or final-state.

Cron: nightly 03:00 UTC (= 22:00 Lima the previous day). The 30-minute
offset from `cleanup_idempotency_keys` (03:30 UTC) spreads I/O.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from app.core.db import session_scope
from app.core.logging import get_logger

logger = get_logger(__name__)

_RETENTION_DAYS = 180

# S608 noqa rationale (applies to each DELETE below): the `interval`
# value is interpolated from a module-level int constant, never from
# user input. SQLAlchemy `text()` is used purely so the literal can
# coexist with other ORM-bound queries in this codebase.

_SQL_PURGE_LEADERBOARD_AUDIT = (
    f"DELETE FROM leaderboard_audit "  # noqa: S608
    f"WHERE created_at < now() - interval '{_RETENTION_DAYS} days'"
)
_SQL_PURGE_REGION_AUDIT = (
    f"DELETE FROM profile_region_change_audit "  # noqa: S608
    f"WHERE changed_at < now() - interval '{_RETENTION_DAYS} days'"
)
_SQL_PURGE_SHADOW_BAN = (
    f"DELETE FROM gamification_shadow_ban "  # noqa: S608
    f"WHERE lifted_at IS NOT NULL "
    f"  AND lifted_at < now() - interval '{_RETENTION_DAYS} days'"
)


async def leaderboard_audit_purge_cron(ctx: dict[str, Any]) -> dict[str, int]:  # noqa: ARG001
    """Purge >180d rows from the three anti-cheat audit tables."""
    deleted: dict[str, int] = {}
    async with session_scope() as session:
        res = await session.execute(text(_SQL_PURGE_LEADERBOARD_AUDIT))
        deleted["leaderboard_audit"] = res.rowcount or 0

        res = await session.execute(text(_SQL_PURGE_REGION_AUDIT))
        deleted["profile_region_change_audit"] = res.rowcount or 0

        res = await session.execute(text(_SQL_PURGE_SHADOW_BAN))
        deleted["gamification_shadow_ban"] = res.rowcount or 0
        await session.commit()

    logger.info(
        "purge.leaderboard_audit",
        leaderboard_audit_rows=deleted["leaderboard_audit"],
        region_change_rows=deleted["profile_region_change_audit"],
        shadow_ban_rows=deleted["gamification_shadow_ban"],
        retention_days=_RETENTION_DAYS,
    )
    return deleted
