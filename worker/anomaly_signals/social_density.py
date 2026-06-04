"""Signal: signup IP /24 overlap density.

The intent (per ADR-0026) is to flag rings of accounts signing up from
the same /24 within a short window. NOVA does not currently persist
signup IP nor referral edges — the backing tables simply do not exist.

This module returns ``None`` so the orchestrator redistributes the 10 %
weight to other available signals. When/if the identity bounded context
starts persisting signup IP + referral graph, replace this body with the
real query.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from worker.anomaly_signals import SignalResult


async def compute(  # noqa: ARG001 — signature parity with sibling signals
    session: AsyncSession, user_id: UUID, window_days: int
) -> SignalResult:
    # Data unavailable — no signup_ip or referral table in schema.
    return None
