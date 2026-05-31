"""SQLAlchemy profile repository."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.profile.domain.entities import UserProfile
from app.profile.infrastructure.models import UserProfileModel


def _from_model(m: UserProfileModel) -> UserProfile:
    return UserProfile(
        user_id=m.user_id, name=m.name, age=m.age, sex=m.sex,  # type: ignore[arg-type]
        units=m.units, weight_kg=m.weight_kg, height_cm=m.height_cm,  # type: ignore[arg-type]
        goal=m.goal, activity_level=m.activity_level,  # type: ignore[arg-type]
        medical_conditions=list(m.medical_conditions or []),
        other_condition=m.other_condition,
        allergies=list(m.allergies or []),
        other_allergy=m.other_allergy,
        country=m.country, region=m.region, locale=m.locale,
        theme=m.theme, onboarding_completed=m.onboarding_completed,  # type: ignore[arg-type]
        updated_at=m.updated_at,
    )


class SqlProfileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def get(self, user_id: UUID) -> UserProfile | None:
        m = await self.s.get(UserProfileModel, user_id)
        return _from_model(m) if m else None

    async def upsert(self, profile: UserProfile) -> None:
        values = {
            "user_id": profile.user_id, "name": profile.name, "age": profile.age,
            "sex": profile.sex, "units": profile.units,
            "weight_kg": profile.weight_kg, "height_cm": profile.height_cm,
            "goal": profile.goal, "activity_level": profile.activity_level,
            "medical_conditions": profile.medical_conditions,
            "other_condition": profile.other_condition,
            "allergies": profile.allergies, "other_allergy": profile.other_allergy,
            "country": profile.country, "region": profile.region,
            "locale": profile.locale, "theme": profile.theme,
            "onboarding_completed": profile.onboarding_completed,
            "updated_at": profile.updated_at,
        }
        stmt = pg_insert(UserProfileModel).values(values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id"],
            set_={k: stmt.excluded[k] for k in values if k != "user_id"},
        )
        await self.s.execute(stmt)
