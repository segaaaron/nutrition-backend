"""SQLAlchemy ORM for plans/plan_days/plan_meals + plan_generation_seeds.

`Plan.days` uses `selectinload`; `PlanDay.meals` uses `selectinload`; the
recipe lookup is deferred to a separate batched call by the application
layer (we do not joinedload PlanMeal→Recipe by default to avoid hauling the
full recipe row into every plan query).
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, BIGINT, JSONB
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.identity.infrastructure.models import Base

# Native Postgres enums (created by migration 0001). `create_type=False`
# prevents SQLAlchemy from issuing CREATE TYPE and forces asyncpg to bind
# values to the column's enum type instead of VARCHAR (otherwise INSERT
# raises DatatypeMismatchError).
_PLAN_TYPE_ENUM = PG_ENUM("day", "week", "month", name="plan_type_enum", create_type=False)
_PLAN_STATUS_ENUM = PG_ENUM(
    "active", "completed", "cancelled", name="plan_status_enum", create_type=False
)
_MEAL_TIME_ENUM = PG_ENUM(
    "breakfast", "lunch", "dinner", "snack", "morning_snack", "afternoon_snack",
    name="meal_time_enum", create_type=False
)


class PlanModel(Base):
    __tablename__ = "plans"
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    type: Mapped[str] = mapped_column(_PLAN_TYPE_ENUM)
    total_days: Mapped[int] = mapped_column(Integer)
    current_day: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(_PLAN_STATUS_ENUM, default="active")
    goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    meals_per_day: Mapped[int] = mapped_column(Integer)
    preferences: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    kcal_target: Mapped[int | None] = mapped_column(Integer, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Per-slot kcal/protein targets (migration 0020). JSON:
    # {"breakfast": {"kcal": 475, "protein_g": 33}, "lunch": {...}, ...}
    # NULL for plans generated before this migration.
    slot_targets: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Daily hydration target in ml (migration 0021). Used to reconstruct
    # water_view on read-back. NULL for pre-migration plans.
    water_ml: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # User locale at creation time (migration 0023). Drives water_view message
    # language on read. NULL for pre-migration plans → defaults to "es".
    locale: Mapped[str | None] = mapped_column(Text, nullable=True)

    days: Mapped[list[PlanDayModel]] = relationship(
        "PlanDayModel",
        cascade="all, delete-orphan",
        order_by="PlanDayModel.day_index",
        lazy="select",
    )


class PlanDayModel(Base):
    __tablename__ = "plan_days"
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    plan_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("plans.id", ondelete="CASCADE")
    )
    day_index: Mapped[int] = mapped_column(Integer)
    date: Mapped[date] = mapped_column(Date)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    # Actual vs target kcal for the day (migration 0020). Computed after
    # portion scaling; NULL for legacy plans.
    kcal_actual: Mapped[int | None] = mapped_column(Integer, nullable=True)
    within_band: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    meals: Mapped[list[PlanMealModel]] = relationship(
        "PlanMealModel",
        cascade="all, delete-orphan",
        order_by="PlanMealModel.meal_time",
        lazy="select",
    )


class PlanMealModel(Base):
    __tablename__ = "plan_meals"
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    plan_day_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("plan_days.id", ondelete="CASCADE")
    )
    meal_time: Mapped[str] = mapped_column(_MEAL_TIME_ENUM)
    recipe_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("recipes.id", ondelete="RESTRICT"), nullable=True
    )
    kcal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    protein_g: Mapped[int | None] = mapped_column(Integer, nullable=True)
    carbs_g: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fat_g: Mapped[int | None] = mapped_column(Integer, nullable=True)
    water_ml: Mapped[int | None] = mapped_column(Integer, nullable=True)
    water_pct: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    # Portion-scaling multiplier vs the recipe's native macros (migration 0018).
    # iOS scales displayed ingredient amounts by this. NULL = legacy → 1.0.
    scaled_factor: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    # User-chosen portion multiplier [0.25, 2.0] (migration 0050 / BE-11).
    # effective_kcal = kcal * user_factor. Stored here; never merged into kcal
    # so the engine value stays clean for plan-intelligence reads (Capa 3).
    user_factor: Mapped[float] = mapped_column(Numeric, default=1.0)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    swapped_from: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)


class PlanMealItemModel(Base):
    """One food item composing a user-built custom meal (migration 0056)."""

    __tablename__ = "plan_meal_items"
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    plan_meal_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("plan_meals.id", ondelete="CASCADE"), nullable=False
    )
    food_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("foods.id", ondelete="RESTRICT"), nullable=True
    )
    free_text_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    grams: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False)
    kcal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    protein_g: Mapped[int | None] = mapped_column(Integer, nullable=True)
    carbs_g: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fat_g: Mapped[int | None] = mapped_column(Integer, nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class PlanGenerationSeedModel(Base):
    __tablename__ = "plan_generation_seeds"
    plan_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("plans.id", ondelete="CASCADE"), primary_key=True
    )
    seed: Mapped[int] = mapped_column(BIGINT)
