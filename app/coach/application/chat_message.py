"""Coach 4-camino orchestration.

Routing:
  1. classifier(text) → intent
  2. if intent == MEDICAL_REDIRECT → Camino 4 template, log metric.
  3. if intent in TEMPLATES → Camino 1 deterministic answer.
  4. else try FAQ embedding lookup (Camino 2, top hit dist < 0.25).
  5. else stream via gpt-4o-mini grounded in ContextWindow (Camino 3).
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from prometheus_client import Counter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.coach.application.context_builder import build_context
from app.coach.application.template_responses import TEMPLATES
from app.coach.domain.entities import Message
from app.coach.domain.events import IntentDetected, MessageReceived
from app.coach.domain.value_objects import ContextWindow, Intent, Role
from app.coach.infrastructure.openai_coach_client import OpenAICoachClient
from app.coach.infrastructure.repositories import SqlConversationRepository
from app.core.event_bus import EventBus
from app.core.logging import get_logger
from app.recipes.infrastructure.openai_embedder import OpenAIEmbedder

log = get_logger("coach.chat")

CAMINO_REQUESTS = Counter(
    "coach_camino_requests_total", "Coach traffic by camino", ["camino"],
)
COACH_MEDICAL_REFUSE = Counter(
    "coach_medical_refuse_total", "Medical refuse-redirects emitted (Camino 4)",
)

FAQ_DISTANCE_MAX = 0.25

MEDICAL_TEMPLATE_ES = (
    "Para esa duda médica consulta a tu médico. Yo solo puedo ayudarte con "
    "nutrición y el plan."
)
MEDICAL_TEMPLATE_EN = (
    "For that medical question please consult your doctor. I can only help "
    "with nutrition and your plan."
)


SYSTEM_PROMPT = (
    "Eres NOVA Coach: nutrición práctica, breve, en el idioma del usuario. "
    "Nunca des diagnóstico médico. Cita siempre el plan activo cuando exista."
)


@dataclass(slots=True)
class ChatMessage:
    session: AsyncSession
    conv_repo: SqlConversationRepository
    classifier: object  # IntentClassifier
    coach: OpenAICoachClient
    bus: EventBus
    embedder: OpenAIEmbedder

    async def stream(
        self,
        *,
        user_id: UUID,
        conv_id: UUID | None,
        user_message: str,
        locale: str = "es",
    ) -> AsyncIterator[str]:
        conv = await self.conv_repo.get_or_create(user_id, conv_id)
        await self.conv_repo.append_message(Message(
            conv_id=conv.id, role=Role.USER, content=user_message,
            created_at=datetime.now(timezone.utc),
        ))

        intent, confidence = await self.classifier.classify(  # type: ignore[attr-defined]
            text=user_message, locale=locale, user_id=user_id,
        )
        await self.bus.publish(IntentDetected(
            user_id=user_id, intent=intent.value, confidence=confidence,
            at=datetime.now(timezone.utc),
        ))

        # --- Camino 4: medical refuse ---
        if intent == Intent.MEDICAL_REDIRECT:
            CAMINO_REQUESTS.labels(camino="refuse").inc()
            COACH_MEDICAL_REFUSE.inc()
            text_out = MEDICAL_TEMPLATE_ES if locale == "es" else MEDICAL_TEMPLATE_EN
            await self._persist_assistant(conv.id, text_out, camino="refuse")
            yield text_out
            return

        # --- Camino 1: deterministic templates ---
        handler = TEMPLATES.get(intent)
        if handler is not None:
            try:
                response = await handler(user_id, self.session, locale)
            except Exception as exc:  # noqa: BLE001
                log.warning("coach.template.failed", err=str(exc))
                response = None
            if response:
                CAMINO_REQUESTS.labels(camino="template").inc()
                await self._persist_assistant(conv.id, response, camino="template")
                yield response
                return

        # --- Camino 2: FAQ embedding cache ---
        faq_answer = await self._try_faq(user_message, locale)
        if faq_answer:
            CAMINO_REQUESTS.labels(camino="cached").inc()
            await self._persist_assistant(conv.id, faq_answer, camino="cached")
            yield faq_answer
            return

        # --- Camino 3: streaming gpt-4o-mini grounded ---
        CAMINO_REQUESTS.labels(camino="mini").inc()
        ctx = await build_context(
            session=self.session, user_id=user_id, conv_id=conv.id,
            user_message=user_message, embedder=self.embedder,
        )
        chunks: list[str] = []
        async for delta in self.coach.stream(
            system_prompt=SYSTEM_PROMPT, context=ctx,
            user_message=user_message, user_id=user_id,
        ):
            chunks.append(delta)
            yield delta
        full = "".join(chunks)
        await self._persist_assistant(conv.id, full, camino="mini")

    async def _try_faq(self, user_message: str, locale: str) -> str | None:
        try:
            emb = await self.embedder.embed(user_message[:200])
        except Exception:  # noqa: BLE001
            return None
        vec_lit = "[" + ",".join(f"{x:.6f}" for x in emb) + "]"
        row = (await self.session.execute(text(f"""
            SELECT answer_translations, embedding <=> '{vec_lit}'::vector AS dist
              FROM coach_faq
             WHERE embedding IS NOT NULL
             ORDER BY embedding <=> '{vec_lit}'::vector
             LIMIT 1
        """))).first()
        if not row or row[1] is None or float(row[1]) > FAQ_DISTANCE_MAX:
            return None
        translations = row[0] or {}
        return translations.get(locale) or translations.get("en")

    async def _persist_assistant(self, conv_id: UUID, content: str, *, camino: str) -> None:
        await self.conv_repo.append_message(Message(
            conv_id=conv_id, role=Role.ASSISTANT, content=content,
            created_at=datetime.now(timezone.utc),
        ))
        await self.bus.publish(MessageReceived(
            conv_id=conv_id, user_id=UUID(int=0),  # filled by caller in production
            intent="", tokens_in=0, tokens_out=len(content) // 4, camino=camino,
            at=datetime.now(timezone.utc),
        ))
