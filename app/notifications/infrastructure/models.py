"""ORM for push_tokens (migration 0003)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import CHAR
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.identity.infrastructure.models import Base


class PushTokenModel(Base):
    __tablename__ = "push_tokens"
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    platform: Mapped[str] = mapped_column(String(16))
    token: Mapped[str] = mapped_column(Text, unique=True)
    # endpoint/p256dh/auth: dead Web Push columns, preserved until next migration
    # cycle drops them. NOVA is mobile-only (FCM); see 2026-06-04 session log.
    endpoint: Mapped[str | None] = mapped_column(Text, nullable=True)
    p256dh: Mapped[str | None] = mapped_column(Text, nullable=True)
    auth: Mapped[str | None] = mapped_column(Text, nullable=True)
    locale: Mapped[str] = mapped_column(CHAR(2), default="en")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invalid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
