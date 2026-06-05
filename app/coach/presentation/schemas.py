"""Pydantic DTOs for the Coach presentation layer."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SseTicketRequest(_Strict):
    conv_id: UUID | None = None


class SseTicketResponse(BaseModel):
    ticket: str
    expires_in_s: int


class ChatRequest(_Strict):
    conv_id: UUID | None = None
    message: str
    # DEPRECATED — locale is now resolved server-side from the
    # ``Accept-Language`` header (Phase 3 of the i18n runtime propagation
    # plan). Field kept for one release cycle to avoid breaking older mobile
    # clients; the value is IGNORED by the server. New clients SHOULD send
    # ``Accept-Language`` instead. Field will be removed once telemetry
    # confirms no client relies on it.
    locale: str = "es"


class ConversationDto(BaseModel):
    id: UUID
    title: str | None
    locale: str
    created_at: datetime


class ConversationsList(BaseModel):
    items: list[ConversationDto]
    next_cursor: str | None


class MessageDto(BaseModel):
    id: UUID
    role: str
    content: str
    created_at: datetime


class MessagesList(BaseModel):
    items: list[MessageDto]
    next_cursor: str | None


class SwapProposalRequest(_Strict):
    plan_meal_id: UUID
    top_k: int = 3
