"""SQLAlchemy ORM — vision_jobs, vision_user_corrections, coach_faq.

Mapped onto migration 0002 (§7 patch).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

# pgvector lacks py.typed marker, runtime works.
from pgvector.sqlalchemy import Vector  # type: ignore[import-untyped]
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.identity.infrastructure.models import Base

# Native Postgres enums — meal_time_enum (migration 0001) +
# vision_job_status_enum (migration 0002). `create_type=False` mandatory
# to avoid asyncpg DatatypeMismatchError on INSERT.
_MEAL_TIME_ENUM = PG_ENUM(
    "breakfast", "lunch", "dinner", "snack", name="meal_time_enum", create_type=False
)
_VISION_JOB_STATUS_ENUM = PG_ENUM(
    "queued",
    "running",
    "completed",
    "failed",
    "cancelled",
    name="vision_job_status_enum",
    create_type=False,
)


class VisionJobModel(Base):
    __tablename__ = "vision_jobs"
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    meal_time: Mapped[str] = mapped_column(_MEAL_TIME_ENUM)
    status: Mapped[str] = mapped_column(_VISION_JOB_STATUS_ENUM, default="queued")
    image_sha256: Mapped[str] = mapped_column(Text)
    image_bytes: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_sha256: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Perceptual hash (63-bit aHash) — column created by migration 0013,
    # producer wired 2026-06-11 (near-dup photo dedup + anomaly signal).
    phash_64: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    detected_items: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class VisionUserCorrectionModel(Base):
    __tablename__ = "vision_user_corrections"
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    detected_name_norm: Mapped[str] = mapped_column(Text, primary_key=True)
    corrected_food_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("foods.id", ondelete="SET NULL"), nullable=True
    )
    corrected_amount_g: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    occurrences: Mapped[int] = mapped_column(Integer, default=1)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CoachFaqModel(Base):
    __tablename__ = "coach_faq"
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    question_en: Mapped[str] = mapped_column(Text)
    answer_translations: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    intent: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class JobDeadLetterModel(Base):
    __tablename__ = "job_deadletter"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_name: Mapped[str] = mapped_column(Text)
    args: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    failed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
