"""Nutritional goals ORM."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.identity.infrastructure.models import Base

# Native Postgres enum — see other ORM models for the
# `create_type=False` rationale (asyncpg DatatypeMismatchError otherwise).
_GOAL_REASON_ENUM = PG_ENUM(
    "onboarding",
    "weight_change",
    "goal_change",
    "plateau",
    "manual",
    name="goal_reason_enum",
    create_type=False,
)


class NutritionalGoalsModel(Base):
    __tablename__ = "nutritional_goals"
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    kcal_min: Mapped[int] = mapped_column(Integer)
    kcal_max: Mapped[int] = mapped_column(Integer)
    protein_g: Mapped[int] = mapped_column(Integer)
    carbs_g: Mapped[int] = mapped_column(Integer)
    fat_g: Mapped[int] = mapped_column(Integer)
    water_ml: Mapped[int] = mapped_column(Integer)
    bmr: Mapped[int] = mapped_column(Integer)
    tdee: Mapped[int] = mapped_column(Integer)
    activity_factor: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    reason: Mapped[str] = mapped_column(_GOAL_REASON_ENUM)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fiber_target_g: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    sodium_target_mg: Mapped[int] = mapped_column(Integer, default=2000, server_default="2000")
