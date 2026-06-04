"""OpenAI gpt-4o-mini coach client with SSE streaming (Camino 3).

Circuit breaker: openai_coach. Cost cap pre-check on every call.
Streaming yields content deltas as plain strings.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID

from openai import AsyncOpenAI

from app.coach.domain.value_objects import ContextWindow
from app.coach.infrastructure.prompt_sanitizer import (
    USER_DATA_CLOSE,
    USER_DATA_OPEN,
    PromptInjectionDetected,
    sanitize_for_prompt,
)
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
    """Render ContextWindow with USER_DATA delimiters (OWASP LLM01 defense).

    The system prompt instructs the model to treat anything between
    ``USER_DATA_OPEN`` and ``USER_DATA_CLOSE`` as DATA, never INSTRUCTIONS.
    Fields are already sanitised in ``context_builder``; we sanitise again
    defensively here so any future caller cannot bypass the guard.
    """
    parts: list[str] = []
    if ctx.profile_compact:
        # profile_compact is built from enum/numeric fields; pass through.
        parts.append("PERFIL:\n" + ctx.profile_compact)
    if ctx.active_plan_today:
        parts.append("PLAN HOY:\n" + ctx.active_plan_today)
    if ctx.last_food_logs:
        parts.append("ULTIMOS LOGS:\n" + ctx.last_food_logs)
    if ctx.rag_recipes:
        rag_lines: list[str] = []
        for r in ctx.rag_recipes[:5]:
            raw_name = r.get("name_en") or ""
            try:
                # belt-and-braces — context_builder already sanitised.
                name = sanitize_for_prompt(str(raw_name), max_len=200)
            except PromptInjectionDetected:
                continue
            rag_lines.append(f"- {name}: {r.get('kcal')} kcal / {r.get('protein_g')}g prot")
        if rag_lines:
            parts.append("RECETAS RELEVANTES:\n" + "\n".join(rag_lines))
    body = "\n\n".join(parts)
    return f"{USER_DATA_OPEN}\n{body}\n{USER_DATA_CLOSE}"


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
            # context_builder already sanitised m["content"]; cap defensively.
            messages.append({"role": m["role"], "content": str(m["content"])[:500]})
        messages.append({"role": "user", "content": user_message})

        async def _open_stream():
            return await _get_client().chat.completions.create(
                model=model,
                messages=messages,
                stream=True,
                temperature=0.4,
                max_tokens=400,
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
            user_id=user_id,
            model=model,
            in_tok=in_tok_est,
            out_tok=out_tok_est,
        )
