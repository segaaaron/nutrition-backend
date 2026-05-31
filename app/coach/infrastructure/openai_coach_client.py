"""OpenAI gpt-4o-mini coach client with SSE streaming (Camino 3).

Circuit breaker: openai_coach. Cost cap pre-check on every call.
Streaming yields content deltas as plain strings.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID

from openai import AsyncOpenAI

from app.coach.domain.value_objects import ContextWindow
from app.core.circuit_breaker import CircuitBreaker
from app.core.config import get_settings
from app.core.cost_cap import estimate_input_cost, pre_check, record_usage
from app.core.logging import get_logger

log = get_logger("coach.client")

_breaker = CircuitBreaker(name="openai_coach", fail_threshold=3, recovery_timeout_s=30)
_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=get_settings().openai_api_key or "sk-test", timeout=30.0)
    return _client


def _render_context(ctx: ContextWindow) -> str:
    parts: list[str] = []
    if ctx.profile_compact:
        parts.append("PERFIL:\n" + ctx.profile_compact)
    if ctx.active_plan_today:
        parts.append("PLAN HOY:\n" + ctx.active_plan_today)
    if ctx.last_food_logs:
        parts.append("ÚLTIMOS LOGS:\n" + ctx.last_food_logs)
    if ctx.rag_recipes:
        rag_str = "\n".join(
            f"- {r.get('name_en')}: {r.get('kcal')} kcal / {r.get('protein_g')}g prot"
            for r in ctx.rag_recipes[:5]
        )
        parts.append("RECETAS RELEVANTES:\n" + rag_str)
    return "\n\n".join(parts)


@dataclass(slots=True)
class OpenAICoachClient:
    model: str | None = None

    def _model(self) -> str:
        return self.model or get_settings().openai_chat_model

    async def stream(
        self,
        *,
        system_prompt: str,
        context: ContextWindow,
        user_message: str,
        user_id: UUID | None,
    ) -> AsyncIterator[str]:
        model = self._model()
        ctx_block = _render_context(context)
        full_input = system_prompt + "\n\n" + ctx_block + "\n\nUSER:\n" + user_message
        est = estimate_input_cost(model, full_input) + 0.001
        await pre_check(user_id=user_id, estimate_usd=est)

        messages = [{"role": "system", "content": system_prompt + "\n\n" + ctx_block}]
        for m in context.last_messages:
            messages.append({"role": m["role"], "content": m["content"][:500]})
        messages.append({"role": "user", "content": user_message})

        async def _open_stream():
            return await _get_client().chat.completions.create(
                model=model, messages=messages, stream=True,
                temperature=0.4, max_tokens=400,
            )

        try:
            stream = await _breaker.call(_open_stream)
        except Exception as exc:  # noqa: BLE001
            log.warning("coach.stream.open_failed", err=str(exc))
            yield "Lo siento, no puedo responder ahora mismo."
            return

        full = []
        async for chunk in stream:
            try:
                delta = chunk.choices[0].delta.content or ""
            except Exception:  # noqa: BLE001
                delta = ""
            if delta:
                full.append(delta)
                yield delta

        # Best-effort token accounting from final aggregated text.
        joined = "".join(full)
        # Approximate output tokens (chars/4) — strict per-call usage isn't
        # part of streaming responses in all SDK versions.
        out_tok_est = max(1, len(joined) // 4)
        in_tok_est = max(1, len(full_input) // 4)
        await record_usage(
            user_id=user_id, model=model, in_tok=in_tok_est, out_tok=out_tok_est,
        )
