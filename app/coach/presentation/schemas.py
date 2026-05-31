"""Pydantic DTOs for the Coach presentation layer."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class SseTicketRequest(BaseModel):
    conv_id: UUID | None = None


class SseTicketResponse(BaseModel):
    ticket: str
    expires_in_s: int


class ChatRequest(BaseModel):
    conv_id: UUID | None = None
    message: str
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


class SwapProposalRequest(BaseModel):
    plan_meal_id: UUID
    top_k: int = 3
