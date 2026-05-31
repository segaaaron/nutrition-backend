"""SQLAlchemy ORM matching Timescale hypertable schema (water_logs/weight_logs)."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.identity.infrastructure.models import Base


class WaterLogModel(Base):
    """Hypertable — primary key is the implicit (time, user_id) chunk key."""

    __tablename__ = "water_logs"
    # SQLAlchemy still needs a primary_key declaration; the actual partitioning
    # is enforced by Timescale's chunking on `time`.
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    ml: Mapped[int] = mapped_column(Integer)
    target_ml: Mapped[int | None] = mapped_column(Integer, nullable=True)


class WeightLogModel(Base):
    __tablename__ = "weight_logs"
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    weight_kg: Mapped[Decimal] = mapped_column(Numeric)
    body_fat_pct: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    waist_cm: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    photo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
