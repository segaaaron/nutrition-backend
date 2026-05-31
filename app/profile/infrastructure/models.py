"""SQLAlchemy ORM model for user_profiles."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.identity.infrastructure.models import Base


class UserProfileModel(Base):
    __tablename__ = "user_profiles"
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sex: Mapped[str | None] = mapped_column(String(8), nullable=True)
    units: Mapped[str] = mapped_column(String(16), default="metric")
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    height_cm: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    goal: Mapped[str | None] = mapped_column(String(16), nullable=True)
    activity_level: Mapped[str | None] = mapped_column(String(24), nullable=True)
    medical_conditions: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    other_condition: Mapped[str | None] = mapped_column(Text, nullable=True)
    allergies: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    other_allergy: Mapped[str | None] = mapped_column(Text, nullable=True)
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    region: Mapped[str | None] = mapped_column(String(5), nullable=True)
    locale: Mapped[str] = mapped_column(String(2), default="en")
    theme: Mapped[str] = mapped_column(String(8), default="light")
    onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
