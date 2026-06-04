"""Signal: account-age vs leaderboard rank.

Designed to flag brand-new accounts (< 7 days old) that have rocketed
into the top-10. Returns ``None`` until a public leaderboard / ranking
projection exists — currently the codebase exposes leaderboard primitives
(``leaderboard_audit``, ``gamification_shadow_ban``) but no actual
``ZADD`` write path (see ADR-0026 §L3 deferral). Without a ranking
source, this signal cannot be computed.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from worker.anomaly_signals import SignalResult


async def compute(  # noqa: ARG001 — signature parity with sibling signals
    session: AsyncSession, user_id: UUID, window_days: int
) -> SignalResult:
    # No ranking source in production — defer until L3 ships a leaderboard
    # ZADD path (see PROJECT_STATE.md "L3 shadow-ban ZADD gate — DEFERRED").
    return None
