"""Adapter exposing the slim eligibility view of the user profile.

Lives in the plan context because it's an anti-corruption layer over the
profile aggregate — only the four fields needed by Layer 1 leak through.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.profile.infrastructure.repositories import SqlProfileRepository


class SqlEligibilityProfileReader:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def get_eligibility_profile(self, user_id: UUID) -> dict | None:
        p = await SqlProfileRepository(self.s).get(user_id)
        if p is None:
            return None
        return {
            "region": p.region or "us",
            "allergies": list(p.allergies or []),
            "conditions": list(p.medical_conditions or []),
            "weight_kg": p.weight_kg,
        }
