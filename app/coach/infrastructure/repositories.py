"""Async SQL repos for the Coach context.

Cursor pagination on conversations + messages (created_at DESC, id DESC).
selectinload not needed here — queries are per-conversation or per-user
with explicit ORDER BY + LIMIT, so no N+1.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.coach.domain.entities import Conversation, Message
from app.coach.domain.value_objects import Role
from app.coach.infrastructure.models import ConversationModel, MessageModel


def _encode_cursor(created_at: datetime, _id: UUID) -> str:
    return base64.urlsafe_b64encode(
        json.dumps([created_at.isoformat(), str(_id)]).encode()
    ).decode()


def _decode_cursor(c: str | None) -> tuple[datetime, UUID] | None:
    if not c:
        return None
    try:
        ts, _id = json.loads(base64.urlsafe_b64decode(c.encode()).decode())
        return (datetime.fromisoformat(ts), UUID(_id))
    except Exception:  # noqa: BLE001
        return None


class SqlConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def get_or_create(self, user_id: UUID, conv_id: UUID | None) -> Conversation:
        if conv_id is not None:
            res = await self.s.execute(
                select(ConversationModel).where(
                    ConversationModel.id == conv_id,
                    ConversationModel.user_id == user_id,
                )
            )
            m = res.scalar_one_or_none()
            if m:
                return Conversation(
                    id=m.id,
                    user_id=m.user_id,
                    title=m.title,
                    locale=m.locale,
                    created_at=m.created_at,
                )
        now = datetime.now(UTC)
        new = ConversationModel(
            id=uuid4(),
            user_id=user_id,
            title=None,
            locale="en",
            created_at=now,
        )
        self.s.add(new)
        await self.s.flush()
        return Conversation(id=new.id, user_id=user_id, locale="en", created_at=now)

    async def append_message(self, msg: Message) -> None:
        self.s.add(
            MessageModel(
                id=msg.id,
                conv_id=msg.conv_id,
                role=msg.role.value,
                content=msg.content,
                tokens_in=msg.tokens_in,
                tokens_out=msg.tokens_out,
                prompt_sha256=msg.prompt_sha256,
                created_at=msg.created_at or datetime.now(UTC),
            )
        )
        await self.s.flush()

    async def list_for_user(
        self,
        user_id: UUID,
        *,
        limit: int,
        cursor: str | None,
    ) -> tuple[list[Conversation], str | None]:
        q = (
            select(ConversationModel)
            .where(ConversationModel.user_id == user_id)
            .order_by(desc(ConversationModel.created_at), desc(ConversationModel.id))
            .limit(limit + 1)
        )
        cur = _decode_cursor(cursor)
        if cur:
            q = q.where(ConversationModel.created_at < cur[0])
        res = await self.s.execute(q)
        rows = list(res.scalars())
        next_cursor: str | None = None
        if len(rows) > limit:
            last = rows[limit - 1]
            next_cursor = _encode_cursor(last.created_at, last.id)
            rows = rows[:limit]
        out = [
            Conversation(
                id=r.id, user_id=r.user_id, title=r.title, locale=r.locale, created_at=r.created_at
            )
            for r in rows
        ]
        return out, next_cursor

    async def get_messages(
        self,
        conv_id: UUID,
        *,
        limit: int,
        cursor: str | None,
    ) -> tuple[list[Message], str | None]:
        q = (
            select(MessageModel)
            .where(MessageModel.conv_id == conv_id)
            .order_by(desc(MessageModel.created_at), desc(MessageModel.id))
            .limit(limit + 1)
        )
        cur = _decode_cursor(cursor)
        if cur:
            q = q.where(MessageModel.created_at < cur[0])
        res = await self.s.execute(q)
        rows = list(res.scalars())
        next_cursor: str | None = None
        if len(rows) > limit:
            last = rows[limit - 1]
            next_cursor = _encode_cursor(last.created_at, last.id)
            rows = rows[:limit]
        out = [
            Message(
                id=r.id,
                conv_id=r.conv_id,
                role=Role(r.role),
                content=r.content,
                tokens_in=r.tokens_in,
                tokens_out=r.tokens_out,
                prompt_sha256=r.prompt_sha256,
                created_at=r.created_at,
            )
            for r in rows
        ]
        return out, next_cursor

    async def delete(self, conv_id: UUID, user_id: UUID) -> None:
        await self.s.execute(
            delete(ConversationModel).where(
                ConversationModel.id == conv_id,
                ConversationModel.user_id == user_id,
            )
        )

    async def recent_messages(self, conv_id: UUID, limit: int = 4) -> list[Message]:
        res = await self.s.execute(
            select(MessageModel)
            .where(MessageModel.conv_id == conv_id)
            .order_by(desc(MessageModel.created_at))
            .limit(limit)
        )
        rows = list(res.scalars())[::-1]
        return [
            Message(
                id=r.id,
                conv_id=r.conv_id,
                role=Role(r.role),
                content=r.content,
                created_at=r.created_at,
            )
            for r in rows
        ]
