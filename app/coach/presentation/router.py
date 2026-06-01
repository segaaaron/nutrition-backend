"""Coach router — SSE chat, ticket auth, conversations, swap proposal.

  POST /coach/sse-ticket                  → mint 30s ticket
  POST /coach/chat?ticket=…|Bearer        → text/event-stream
  GET  /coach/conversations               → cursor paginated list
  GET  /coach/conversations/{id}/messages → cursor paginated messages
  DELETE /coach/conversations/{id}
  POST /coach/swap                        → list of 3 swap candidates

SSE backpressure: per-worker counter `coach:sse:active` capped at 50.
Rate limit: 30/min/user via Redis counter.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Annotated, AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from app.coach.application.chat_message import ChatMessage
from app.coach.application.propose_swap import ProposeSwap
from app.coach.infrastructure.intent_classifier import HybridIntentClassifier
from app.coach.infrastructure.openai_coach_client import OpenAICoachClient
from app.coach.infrastructure.repositories import SqlConversationRepository
from app.coach.infrastructure.sse_ticket import consume, mint
from app.coach.presentation.schemas import (
    ChatRequest,
    ConversationDto,
    ConversationsList,
    MessageDto,
    MessagesList,
    SseTicketRequest,
    SseTicketResponse,
    SwapProposalRequest,
)
from app.core.errors import RateLimited
from app.core.event_bus import get_event_bus
from app.core.redis import get_redis
from app.identity.presentation.dependencies import CurrentUserDep, SessionDep
from app.recipes.infrastructure.openai_embedder import OpenAIEmbedder

router = APIRouter(prefix="/coach", tags=["coach"])

SSE_MAX_CONCURRENT = 50
SSE_COUNTER_KEY = "coach:sse:active"
RATE_LIMIT_PER_MIN = 30


async def _check_rate(user_id: UUID) -> None:
    r = get_redis()
    minute = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
    key = f"rl:coach:{user_id}:{minute}"
    pipe = r.pipeline()
    pipe.incr(key)
    pipe.expire(key, 70)
    n, _ = await pipe.execute()
    if int(n) > RATE_LIMIT_PER_MIN:
        raise RateLimited("coach_per_min_cap", retry_after_s=60)


@router.post("/sse-ticket", response_model=SseTicketResponse)
async def sse_ticket(
    body: SseTicketRequest, current_user: CurrentUserDep, session: SessionDep,
) -> SseTicketResponse:
    repo = SqlConversationRepository(session)
    conv = await repo.get_or_create(current_user, body.conv_id)
    token = await mint(session, user_id=current_user, conv_id=conv.id)
    return SseTicketResponse(ticket=token, expires_in_s=30)


@router.post("/chat")
async def chat(
    body: ChatRequest,
    session: SessionDep,
    ticket: Annotated[str | None, Query()] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> StreamingResponse:
    # Ticket-only auth for this endpoint (browser EventSource can't send Bearer).
    user_id, conv_id = await consume(session, token=ticket or "")
    await _check_rate(user_id)

    r = get_redis()
    n_active = int(await r.incr(SSE_COUNTER_KEY))
    if n_active > SSE_MAX_CONCURRENT:
        await r.decr(SSE_COUNTER_KEY)
        raise RateLimited("sse_backpressure", retry_after_s=10)

    chat_uc = ChatMessage(
        session=session,
        conv_repo=SqlConversationRepository(session),
        classifier=HybridIntentClassifier(),
        coach=OpenAICoachClient(),
        bus=get_event_bus(),
        embedder=OpenAIEmbedder(),
    )

    async def _gen() -> AsyncIterator[bytes]:
        try:
            async for chunk in chat_uc.stream(
                user_id=user_id, conv_id=conv_id,
                user_message=body.message, locale=body.locale,
            ):
                # Format as SSE data event.
                payload = chunk.replace("\n", " ")
                yield f"data: {payload}\n\n".encode()
            yield b"event: done\ndata: 1\n\n"
        finally:
            await r.decr(SSE_COUNTER_KEY)

    return StreamingResponse(_gen(), media_type="text/event-stream")


@router.get("/conversations", response_model=ConversationsList)
async def list_conversations(
    current_user: CurrentUserDep, session: SessionDep,
    limit: int = Query(20, ge=1, le=50),
    cursor: str | None = Query(None),
) -> ConversationsList:
    repo = SqlConversationRepository(session)
    items, nxt = await repo.list_for_user(current_user, limit=limit, cursor=cursor)
    return ConversationsList(
        items=[
            ConversationDto(id=c.id, title=c.title, locale=c.locale, created_at=c.created_at)  # type: ignore[arg-type]
            for c in items
        ],
        next_cursor=nxt,
    )


@router.get("/conversations/{conv_id}/messages", response_model=MessagesList)
async def list_messages(
    conv_id: UUID, current_user: CurrentUserDep, session: SessionDep,
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = Query(None),
) -> MessagesList:
    repo = SqlConversationRepository(session)
    msgs, nxt = await repo.get_messages(conv_id, limit=limit, cursor=cursor)
    return MessagesList(
        items=[
            MessageDto(id=m.id, role=m.role.value, content=m.content, created_at=m.created_at)  # type: ignore[arg-type]
            for m in msgs
        ],
        next_cursor=nxt,
    )


@router.delete(
    "/conversations/{conv_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_conversation(
    conv_id: UUID, current_user: CurrentUserDep, session: SessionDep,
) -> Response:
    await SqlConversationRepository(session).delete(conv_id, current_user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class SwapResponse(BaseModel):
    candidates: list[dict]


@router.post("/swap", response_model=SwapResponse)
async def propose_swap(
    body: SwapProposalRequest, current_user: CurrentUserDep, session: SessionDep,
) -> SwapResponse:
    uc = ProposeSwap(session=session)
    candidates = await uc(user_id=current_user, plan_meal_id=body.plan_meal_id, top_k=body.top_k)
    return SwapResponse(candidates=candidates)
