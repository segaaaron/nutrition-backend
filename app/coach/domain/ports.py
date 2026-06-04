"""Coach ports — protocols for repositories + AI providers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol
from uuid import UUID

from app.coach.domain.entities import Conversation, Message
from app.coach.domain.value_objects import ContextWindow, Intent


class ConversationRepository(Protocol):
    async def get_or_create(self, user_id: UUID, conv_id: UUID | None) -> Conversation: ...
    async def append_message(self, msg: Message) -> None: ...
    async def list_for_user(
        self,
        user_id: UUID,
        *,
        limit: int,
        cursor: str | None,
    ) -> tuple[list[Conversation], str | None]: ...
    async def get_messages(
        self,
        conv_id: UUID,
        *,
        limit: int,
        cursor: str | None,
    ) -> tuple[list[Message], str | None]: ...
    async def delete(self, conv_id: UUID, user_id: UUID) -> None: ...


class IntentClassifier(Protocol):
    async def classify(
        self, *, text: str, locale: str, user_id: UUID | None
    ) -> tuple[Intent, float]: ...


class CoachProvider(Protocol):
    async def stream(
        self,
        *,
        system_prompt: str,
        context: ContextWindow,
        user_message: str,
        user_id: UUID | None,
    ) -> AsyncIterator[str]: ...
