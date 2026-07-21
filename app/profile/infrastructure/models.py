"""SQLAlchemy ORM model for user_profiles."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.identity.infrastructure.models import Base

# Native Postgres enums (created by migration 0001 — `create_type=False`
# tells SQLAlchemy NOT to attempt CREATE TYPE on metadata.create_all and
# NOT to bind values as VARCHAR. Without this the asyncpg dialect sends
# `$N::VARCHAR` which Postgres refuses against an enum column
# (DatatypeMismatchError).
_SEX_ENUM = PG_ENUM("male", "female", name="sex_enum", create_type=False)
_UNITS_ENUM = PG_ENUM("metric", "imperial", name="units_enum", create_type=False)
_GOAL_ENUM = PG_ENUM(
    "weight_loss",
    "maintain",
    "muscle_gain",
    "weight_gain",
    "health",
    name="goal_enum",
    create_type=False,
)
_ACTIVITY_LEVEL_ENUM = PG_ENUM(
    "sedentary",
    "lightly_active",
    "moderately_active",
    "very_active",
    "extra_active",
    name="activity_level_enum",
    create_type=False,
)
_THEME_ENUM = PG_ENUM("light", "dark", name="theme_enum", create_type=False)
_ALLERGEN_ENUM = PG_ENUM(
    "dairy",
    "gluten",
    "tree_nuts",
    "peanuts",
    "shellfish",
    "fish",
    "egg",
    "soy",
    "sesame",
    "celery",
    "mustard",
    "lupin",
    "sulphites",
    "molluscs",
    name="allergen_enum",
    create_type=False,
)


class UserProfileModel(Base):
    __tablename__ = "user_profiles"
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sex: Mapped[str | None] = mapped_column(_SEX_ENUM, nullable=True)
    units: Mapped[str] = mapped_column(_UNITS_ENUM, default="metric")
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    height_cm: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    goal_weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    goal: Mapped[str | None] = mapped_column(_GOAL_ENUM, nullable=True)
    activity_level: Mapped[str | None] = mapped_column(_ACTIVITY_LEVEL_ENUM, nullable=True)
    medical_conditions: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    other_condition: Mapped[str | None] = mapped_column(Text, nullable=True)
    allergies: Mapped[list[str]] = mapped_column(ARRAY(_ALLERGEN_ENUM), default=list)
    other_allergy: Mapped[str | None] = mapped_column(Text, nullable=True)
    disliked_ingredients: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default="{}"
    )
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    region: Mapped[str | None] = mapped_column(String(5), nullable=True)
    locale: Mapped[str] = mapped_column(String(2), default="en")
    theme: Mapped[str] = mapped_column(_THEME_ENUM, default="light")
    onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    # --- Onboarding extensions (migration 0010) ---
    dietary_pattern: Mapped[str | None] = mapped_column(Text, nullable=True)
    bodyfat_pct: Mapped[Decimal | None] = mapped_column(Numeric(4, 2), nullable=True)
    trimester: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_exclusively_breastfeeding: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
