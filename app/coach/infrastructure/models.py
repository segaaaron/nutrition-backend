"""SQLAlchemy ORM — coach_conversations, coach_messages, coach_sse_tickets."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import CHAR, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.identity.infrastructure.models import Base


class ConversationModel(Base):
    __tablename__ = "coach_conversations"
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    locale: Mapped[str] = mapped_column(CHAR(2), default="en")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MessageModel(Base):
    __tablename__ = "coach_messages"
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    conv_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("coach_conversations.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prompt_sha256: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SseTicketModel(Base):
    __tablename__ = "coach_sse_tickets"
    token_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    conv_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("coach_conversations.id", ondelete="CASCADE")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
