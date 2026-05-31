"""SQLAlchemy nutritional-goals repository + adapters for ProfileReader / TrackingReader."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.nutrition.domain.state_machine import NutritionalGoals
from app.nutrition.infrastructure.models import NutritionalGoalsModel
from app.profile.infrastructure.repositories import SqlProfileRepository


def _from_model(m: NutritionalGoalsModel) -> NutritionalGoals:
    return NutritionalGoals(
        id=m.id, user_id=m.user_id, kcal_min=m.kcal_min, kcal_max=m.kcal_max,
        protein_g=m.protein_g, carbs_g=m.carbs_g, fat_g=m.fat_g,
        water_ml=m.water_ml, bmr=m.bmr, tdee=m.tdee,
        activity_factor=m.activity_factor, reason=m.reason,  # type: ignore[arg-type]
        valid_from=m.valid_from, valid_to=m.valid_to,
    )


class SqlNutritionalGoalsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def get_current(self, user_id: UUID) -> NutritionalGoals | None:
        stmt = select(NutritionalGoalsModel).where(
            NutritionalGoalsModel.user_id == user_id,
            NutritionalGoalsModel.valid_to.is_(None),
        )
        m = (await self.s.execute(stmt)).scalar_one_or_none()
        return _from_model(m) if m else None

    async def list_history(self, user_id: UUID, limit: int) -> list[NutritionalGoals]:
        stmt = (
            select(NutritionalGoalsModel)
            .where(NutritionalGoalsModel.user_id == user_id)
            .order_by(NutritionalGoalsModel.valid_from.desc())
            .limit(limit)
        )
        rows = (await self.s.execute(stmt)).scalars().all()
        return [_from_model(m) for m in rows]

    async def expire_current_and_insert(
        self, user_id: UUID, new_goals: NutritionalGoals,
    ) -> NutritionalGoals:
        now = new_goals.valid_from
        await self.s.execute(
            update(NutritionalGoalsModel).where(
                NutritionalGoalsModel.user_id == user_id,
                NutritionalGoalsModel.valid_to.is_(None),
            ).values(valid_to=now),
        )
        m = NutritionalGoalsModel(
            id=new_goals.id, user_id=new_goals.user_id,
            kcal_min=new_goals.kcal_min, kcal_max=new_goals.kcal_max,
            protein_g=new_goals.protein_g, carbs_g=new_goals.carbs_g, fat_g=new_goals.fat_g,
            water_ml=new_goals.water_ml, bmr=new_goals.bmr, tdee=new_goals.tdee,
            activity_factor=new_goals.activity_factor, reason=new_goals.reason,
            valid_from=new_goals.valid_from, valid_to=None,
            created_at=now,
        )
        self.s.add(m)
        await self.s.flush()
        return new_goals


class SqlProfileReader:
    """Adapter from profile bounded context into the ProfileReader port."""

    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def biometrics(self, user_id: UUID) -> dict | None:
        p = await SqlProfileRepository(self.s).get(user_id)
        if p is None:
            return None
        return {
            "weight_kg": p.weight_kg, "height_cm": p.height_cm, "age": p.age,
            "sex": p.sex, "goal": p.goal, "activity_level": p.activity_level,
        }


class SqlTrackingReader:
    """Reads weight/intake series via raw SQL — keeps tracking context independent."""

    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def weight_series_14d(self, user_id: UUID) -> list[tuple[int, float]]:
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=14)
        rows = (await self.s.execute(text("""
            SELECT EXTRACT(EPOCH FROM (time - :cutoff))::int / 86400 AS day_index, weight_kg
              FROM weight_logs
             WHERE user_id = :uid AND time >= :cutoff
             ORDER BY time
        """), {"uid": user_id, "cutoff": cutoff})).all()
        return [(int(r[0]), float(r[1])) for r in rows]

    async def kcal_in_14d(self, user_id: UUID) -> list[int]:
        cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=14)).date()
        rows = (await self.s.execute(text("""
            SELECT date, COALESCE(SUM(kcal), 0)::int AS kcal_total
              FROM food_logs
             WHERE user_id = :uid AND date >= :cutoff
             GROUP BY date
             ORDER BY date
        """), {"uid": user_id, "cutoff": cutoff})).all()
        return [int(r[1]) for r in rows]
