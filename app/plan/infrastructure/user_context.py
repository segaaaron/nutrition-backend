"""Aggregates user targets + profile snapshot for plan generation.

Anti-corruption layer over nutrition + profile bounded contexts.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.nutrition.infrastructure.repositories import SqlNutritionalGoalsRepository
from app.profile.infrastructure.repositories import SqlProfileRepository


class SqlUserContext:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def get_user_targets(self, user_id: UUID) -> dict:
        goals = await SqlNutritionalGoalsRepository(self.s).get_current(user_id)
        if goals is None:
            return {}
        return {
            "kcal_min": goals.kcal_min,
            "kcal_max": goals.kcal_max,
            "protein_g": goals.protein_g,
            "carbs_g": goals.carbs_g,
            "fat_g": goals.fat_g,
            "water_ml": goals.water_ml,
        }

    async def get_user_profile_snapshot(self, user_id: UUID) -> dict:
        p = await SqlProfileRepository(self.s).get(user_id)
        if p is None:
            return {}
        return {
            "country": p.country,
            "region": p.region,
            "locale": p.locale,
            "goal": p.goal,
            "preferences": [],
            "allergies": list(p.allergies or []),
            "conditions": list(p.medical_conditions or []),
        }

    async def get_ranking_context(self, user_id: UUID) -> dict:
        p = await SqlProfileRepository(self.s).get(user_id)
        if p is None:
            return {}
        return {
            "country": p.country,
            "prep_time_pref_min": None,
        }
