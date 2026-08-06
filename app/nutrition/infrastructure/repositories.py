"""SQLAlchemy nutritional-goals repository + adapters for ProfileReader / TrackingReader."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.nutrition.domain.state_machine import NutritionalGoals
from app.nutrition.infrastructure.models import NutritionalGoalsModel
from app.profile.infrastructure.repositories import SqlProfileRepository


def _from_model(m: NutritionalGoalsModel) -> NutritionalGoals:
    return NutritionalGoals(
        id=m.id,
        user_id=m.user_id,
        kcal_min=m.kcal_min,
        kcal_max=m.kcal_max,
        protein_g=m.protein_g,
        carbs_g=m.carbs_g,
        fat_g=m.fat_g,
        water_ml=m.water_ml,
        bmr=m.bmr,
        tdee=m.tdee,
        activity_factor=m.activity_factor,
        reason=m.reason,  # type: ignore[arg-type]
        valid_from=m.valid_from,
        valid_to=m.valid_to,
        fiber_target_g=m.fiber_target_g,
        sodium_target_mg=m.sodium_target_mg,
    )


class SqlNutritionalGoalsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def acquire_user_lock(self, user_id: UUID) -> None:
        """Sprint 3 D5 — per-user serialisation for recalibration.

        `pg_advisory_xact_lock` takes a `bigint`; we project the UUID
        into 63 bits via `hashtextextended` on the canonical string form.
        The lock is auto-released at transaction end (commit or
        rollback), so callers do not need to free it explicitly.

        Trade-off: hashtextextended collisions are statistically possible
        (~one per 2^63 keys) and would cause unrelated users to serialise
        briefly. Acceptable: the worst case is a short queue, not a
        correctness violation — `one_current_goals` remains the authority.
        """
        await self.s.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
            {"k": f"nutrition.recalibrate:{user_id}"},
        )

    async def get_current(self, user_id: UUID) -> NutritionalGoals | None:
        stmt = select(NutritionalGoalsModel).where(
            NutritionalGoalsModel.user_id == user_id,
            NutritionalGoalsModel.valid_to.is_(None),
        )
        m = (await self.s.execute(stmt)).scalar_one_or_none()
        return _from_model(m) if m else None

    async def list_history(
        self,
        user_id: UUID,
        limit: int,
        *,
        cursor: datetime | None = None,
    ) -> list[NutritionalGoals]:
        stmt = select(NutritionalGoalsModel).where(
            NutritionalGoalsModel.user_id == user_id
        )
        if cursor is not None:
            # cursor is the valid_from of the last seen item (exclusive)
            stmt = stmt.where(NutritionalGoalsModel.valid_from < cursor)
        stmt = stmt.order_by(NutritionalGoalsModel.valid_from.desc()).limit(limit)
        rows = (await self.s.execute(stmt)).scalars().all()
        return [_from_model(m) for m in rows]

    async def expire_current_and_insert(
        self,
        user_id: UUID,
        new_goals: NutritionalGoals,
    ) -> NutritionalGoals:
        now = new_goals.valid_from
        await self.s.execute(
            update(NutritionalGoalsModel)
            .where(
                NutritionalGoalsModel.user_id == user_id,
                NutritionalGoalsModel.valid_to.is_(None),
            )
            .values(valid_to=now),
        )
        m = NutritionalGoalsModel(
            id=new_goals.id,
            user_id=new_goals.user_id,
            kcal_min=new_goals.kcal_min,
            kcal_max=new_goals.kcal_max,
            protein_g=new_goals.protein_g,
            carbs_g=new_goals.carbs_g,
            fat_g=new_goals.fat_g,
            water_ml=new_goals.water_ml,
            bmr=new_goals.bmr,
            tdee=new_goals.tdee,
            activity_factor=new_goals.activity_factor,
            reason=new_goals.reason,
            valid_from=new_goals.valid_from,
            valid_to=None,
            created_at=now,
            fiber_target_g=new_goals.fiber_target_g,
            sodium_target_mg=new_goals.sodium_target_mg,
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
            "weight_kg": p.weight_kg,
            "height_cm": p.height_cm,
            "age": p.age,
            "sex": p.sex,
            "goal": p.goal,
            "activity_level": p.activity_level,
            # D1 — feed condition list into hydration so CKD/CHF caps activate.
            "conditions": frozenset(p.medical_conditions or ()),
            # H1.4 — feed trimester into pregnancy kcal surplus (IOM DRI 2002).
            "trimester": p.trimester,
            # NOVA hydration v2 — extra signals for `calculate_water_target`.
            # region drives the LatAm hot-season climate modifier (Oct-Mar).
            # pregnant / lactating drive +300 / +700 ml bumps respectively.
            "region": p.region,
            "pregnant": p.trimester is not None,
            # `lactating` reflects the user's lactation condition, not the
            # exclusive-vs-parcial flag. A mother who is partially
            # breastfeeding still needs the +700 ml/day hydration bump
            # (IOM DRI 2002). The exclusive flag controls the kcal surplus
            # magnitude (+500 exclusive vs +330 partial) and is forwarded
            # separately below.
            "lactating": "lactation" in (p.medical_conditions or ()),
            "is_exclusively_breastfeeding": p.is_exclusively_breastfeeding,
        }


class SqlTrackingReader:
    """Reads weight/intake series via raw SQL — keeps tracking context independent."""

    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def weight_series_14d(self, user_id: UUID) -> list[tuple[int, float]]:
        cutoff = datetime.now(tz=UTC) - timedelta(days=14)
        rows = (
            await self.s.execute(
                text(
                    """
            SELECT EXTRACT(EPOCH FROM (time - :cutoff))::int / 86400 AS day_index, weight_kg
              FROM weight_logs
             WHERE user_id = :uid AND time >= :cutoff
             ORDER BY time
        """
                ),
                {"uid": user_id, "cutoff": cutoff},
            )
        ).all()
        return [(int(r[0]), float(r[1])) for r in rows]

    async def kcal_in_14d(self, user_id: UUID) -> list[int]:
        cutoff = (datetime.now(tz=UTC) - timedelta(days=14)).date()
        rows = (
            await self.s.execute(
                text(
                    """
            SELECT date, COALESCE(SUM(kcal), 0)::int AS kcal_total
              FROM food_logs
             WHERE user_id = :uid AND date >= :cutoff
             GROUP BY date
             ORDER BY date
        """
                ),
                {"uid": user_id, "cutoff": cutoff},
            )
        ).all()
        return [int(r[1]) for r in rows]
