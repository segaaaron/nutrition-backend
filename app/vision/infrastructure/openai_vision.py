"""OpenAI vision adapter — gpt-4o-2024-08-06 with strict JSON schema output.

Wrapped in the generic CircuitBreaker (3 fails / 30s recovery). Cost cap is
pre-checked using a fixed 765-token vision-image estimate (1024x1024 at
high detail per OpenAI's published image-token formula) plus a tokenised
prompt body. Latency budget: 30s timeout, 2× exponential retry.

PII: detected food item names are NOT logged; only counts + duration land in
structured logs (validation #9).
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from openai import AsyncOpenAI

from app.core.circuit_breaker import CircuitBreaker
from app.core.config import get_settings
from app.core.cost_cap import estimate_input_cost, pre_check, record_usage
from app.core.errors import UpstreamError
from app.core.logging import get_logger
from app.vision.domain.entities import DetectedFoodItem

log = get_logger("vision.openai")

_client: AsyncOpenAI | None = None
_breaker = CircuitBreaker(name="openai_vision", fail_threshold=3, recovery_timeout_s=30)

# 1024x1024 high-detail image ≈ 765 input tokens (OpenAI public formula).
IMAGE_TOKEN_ESTIMATE = 765
TIMEOUT_S = 30.0
MAX_RETRIES = 2

VISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "estimated_amount_g": {"type": "number"},
                    "kcal": {"type": "integer"},
                    "protein_g": {"type": "integer"},
                    "carbs_g": {"type": "integer"},
                    "fat_g": {"type": "integer"},
                    "confidence": {"type": "number"},
                },
                "required": [
                    "name", "estimated_amount_g", "kcal", "protein_g",
                    "carbs_g", "fat_g", "confidence",
                ],
            },
        },
    },
    "required": ["items"],
}


def _system_prompt(locale: str, region: str) -> str:
    return (
        "Eres un nutricionista clínico LatAm/US/EU. Analiza la foto del plato y "
        "devuelve solo ingredientes visibles con macros estimados per ítem, en gramos. "
        "Usa USDA FDC como referencia. Confidence en 0..1. "
        f"Locale={locale}. Region={region}. "
        "Devuelve estricto JSON conforme al esquema; nunca texto libre."
    )


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=get_settings().openai_api_key or "sk-test",
            timeout=TIMEOUT_S,
        )
    return _client


@dataclass(slots=True)
class OpenAIVisionProvider:
    """Implements VisionProvider port."""

    model: str | None = None

    def _model(self) -> str:
        return self.model or get_settings().openai_vision_model

    async def recognise(
        self,
        *,
        image_bytes: bytes,
        mime: str,
        user_id: UUID | None,
        locale: str,
        region: str,
    ) -> tuple[list[DetectedFoodItem], str]:
        model = self._model()
        sys_prompt = _system_prompt(locale, region)
        prompt_sha = hashlib.sha256(sys_prompt.encode()).hexdigest()

        # Cost cap pre-check. Vision call ≈ 765 image tokens + prompt + ~150 out.
        text_est = estimate_input_cost(model, sys_prompt)
        image_est = (IMAGE_TOKEN_ESTIMATE / 1_000_000.0) * 2.75  # input pricing
        est = text_est + image_est + 0.002  # add output buffer
        await pre_check(user_id=user_id, estimate_usd=est)

        b64 = base64.b64encode(image_bytes).decode()
        data_url = f"data:{mime};base64,{b64}"

        async def _call() -> dict:
            resp = await _get_client().chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": [
                        {"type": "text", "text": "Analiza la foto y lista los ítems."},
                        {"type": "image_url", "image_url": {"url": data_url, "detail": "high"}},
                    ]},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "vision_items",
                        "strict": True,
                        "schema": VISION_SCHEMA,
                    },
                },
                temperature=0.1,
            )
            content = resp.choices[0].message.content or "{}"
            usage = resp.usage
            await record_usage(
                user_id=user_id, model=model,
                in_tok=(getattr(usage, "prompt_tokens", 0) if usage else IMAGE_TOKEN_ESTIMATE),
                out_tok=(getattr(usage, "completion_tokens", 0) if usage else 150),
            )
            return json.loads(content)

        attempt = 0
        last_exc: Exception | None = None
        while attempt <= MAX_RETRIES:
            try:
                raw = await _breaker.call(_call)
                items = _parse_items(raw)
                # Logs intentionally exclude item names (PII).
                log.info(
                    "vision.recognise.ok",
                    n_items=len(items), attempt=attempt, prompt_sha=prompt_sha[:8],
                )
                return items, prompt_sha
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                attempt += 1
                if attempt > MAX_RETRIES:
                    break
                await asyncio.sleep(0.5 * (2 ** (attempt - 1)))

        log.warning("vision.recognise.failed", error=str(last_exc))
        raise UpstreamError(f"vision_failed:{last_exc!s}")


def _parse_items(raw: dict) -> list[DetectedFoodItem]:
    out: list[DetectedFoodItem] = []
    for r in raw.get("items", []) or []:
        try:
            out.append(DetectedFoodItem(
                name=str(r["name"])[:120],
                estimated_amount_g=Decimal(str(r["estimated_amount_g"])),
                kcal=max(0, int(r["kcal"])),
                protein_g=max(0, int(r["protein_g"])),
                carbs_g=max(0, int(r["carbs_g"])),
                fat_g=max(0, int(r["fat_g"])),
                confidence=max(0.0, min(1.0, float(r["confidence"]))),
            ))
        except Exception:  # noqa: BLE001 — skip malformed rows
            continue
    return out
