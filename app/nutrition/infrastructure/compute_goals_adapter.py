"""Adapter wiring the profile-owned `ComputeGoalsPort` to nutrition's
`ComputeInitialGoals` use case, bound to a single SQLAlchemy session.

This is the atomic replacement for the previous event-driven baseline
trigger (`BiometricsChanged` → `_on_biometrics_changed`), which opened
a SECOND session that read the profile row BEFORE the outer transaction
had committed — silently logging `profile_not_found` and leaving
`nutritional_goals` empty. With this adapter the baseline insert
participates in the same transaction as the profile upsert.

Kept in nutrition/infrastructure (not profile/) so the profile
bounded context only depends on its own `ComputeGoalsPort` Protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.event_bus import EventBus
from app.nutrition.application.use_cases import ComputeInitialGoals
from app.nutrition.infrastructure.repositories import (
    SqlNutritionalGoalsRepository,
    SqlProfileReader,
)


@dataclass(slots=True)
class InlineComputeGoals:
    """`ComputeGoalsPort` implementation bound to a request-scoped session."""

    session: AsyncSession
    bus: EventBus

    async def __call__(self, *, user_id: UUID) -> None:
        uc = ComputeInitialGoals(
            profile_reader=SqlProfileReader(self.session),
            goals_repo=SqlNutritionalGoalsRepository(self.session),
            bus=self.bus,
        )
        await uc(user_id=user_id)
