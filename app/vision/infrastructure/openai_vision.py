"""OpenAI vision adapter — hybrid cascade (gpt-4o-mini → gpt-4o full).

Cost strategy (ADR-0004 §vision-cascade):
  1. Auto-select image `detail` based on dimensions (small → "low" 85 tok,
     else → "high" 765 tok). OpenAI public image-token formula.
  2. Call the cheap primary model first (`openai_vision_model_primary`,
     default gpt-4o-mini). Capped via `max_tokens` to prevent runaway output.
  3. If the primary's avg confidence < threshold, OR min < 0.5, OR items is
     empty → escalate to `openai_vision_model_fallback` (gpt-4o full).
  4. Both calls accounted for in cost-cap + Prometheus.

Backward compat: if primary == fallback, this collapses to a single call
identical to the legacy behaviour.

Wrapped in the generic CircuitBreaker (3 fails / 30s recovery). Cost cap is
pre-checked per call using the actual model price.

PII: detected food item names are NOT logged; only counts + duration + the
cascade decision land in structured logs.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from statistics import fmean
from typing import Any, Literal
from uuid import UUID

from openai import AsyncOpenAI

from app.core.circuit_breaker import CircuitBreaker
from app.core.config import get_settings
from app.core.cost_cap import (
    _price_input,
    _price_output,
    estimate_input_cost,
    pre_check,
    record_usage,
)
from app.core.errors import UpstreamError
from app.core.logging import get_logger
from app.core.metrics import (
    VISION_DETAIL_LEVEL,
    VISION_FALLBACK,
    VISION_PARSE_ERRORS,
    VISION_PRIMARY_OK,
)
from app.vision.domain.entities import DetectedFoodItem

log = get_logger("vision.openai")

_client: AsyncOpenAI | None = None
_breaker = CircuitBreaker(name="openai_vision", fail_threshold=3, recovery_timeout_s=30)

# OpenAI public image-token formula reference points.
# 1024x1024 high-detail image ≈ 765 input tokens; low-detail flat ≈ 85.
IMAGE_TOKEN_HIGH = 765
IMAGE_TOKEN_LOW = 85
TIMEOUT_S = 30.0
MAX_RETRIES = 2

# Confidence floor: even if the average is good, a single very low-confidence
# item should trigger escalation. Hard-coded because it is a domain-quality
# guardrail, not a tuning knob.
MIN_ITEM_CONFIDENCE_FLOOR = 0.5

DetailLevel = Literal["low", "high"]

PREFILTER_MODEL = "gpt-4o-mini"
PREFILTER_MAX_OUTPUT_TOKENS = 30
# Tiny safety buffer over the ~$0.0001 real cost (image 85 tok + prompt ~150
# tok + 30 out tok at gpt-4o-mini pricing). CLAUDE.md #2 — Decimal in cost
# math.
PREFILTER_COST_ESTIMATE_USD = 0.0002

PREFILTER_VALID_REASONS: frozenset[str] = frozenset(
    {
        "food",
        "drink_caloric",
        "ingredient",
        "supplement",
        "low_kcal",
        "non_food",
        "empty_plate",
        "uncertain",
    }
)

PREFILTER_SYSTEM_PROMPT = (
    "Eres clasificador binario de imagenes nutricionales.\n\n"
    'Responde SOLO con JSON: {"accept": true|false, "reason": "<short_tag>"}\n\n'
    "ACCEPT (accept=true) si la imagen muestra:\n"
    "- Alimento listo para comer (plato, fruta, vegetal, snack)\n"
    "- Bebida con >20 kcal (jugo, smoothie, leche, alcohol, shake servido)\n"
    "- Ingrediente identificable en cantidad consumible\n\n"
    "REJECT (accept=false) si muestra:\n"
    "- Pills, capsulas, polvos en envase, frascos de suplementos/vitaminas\n"
    "- Agua, cafe negro, te sin azucar (<=20 kcal)\n"
    "- Objetos no alimenticios, paisajes, personas sin comida\n"
    "- Plato vacio\n\n"
    "Si tienes duda, prefiere accept=true.\n\n"
    'Tags validos para reason: "food", "drink_caloric", "ingredient", '
    '"supplement", "low_kcal", "non_food", "empty_plate", "uncertain".'
)

PREFILTER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "accept": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["accept", "reason"],
}


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
                    "name",
                    "estimated_amount_g",
                    "kcal",
                    "protein_g",
                    "carbs_g",
                    "fat_g",
                    "confidence",
                ],
            },
        },
    },
    "required": ["items"],
}


def _system_prompt(locale: str, region: str) -> str:
    return (
        "Eres un experto en nutrición LatAm/US/EU. Analiza la foto del plato y "
        "devuelve solo ingredientes visibles con macros estimados per ítem, en gramos. "
        "Usa USDA FDC como referencia. Confidence en 0..1. "
        f"Locale={locale}. Region={region}. "
        "Devuelve estricto JSON conforme al esquema; nunca texto libre."
    )


def _get_client() -> AsyncOpenAI:
    global _client  # noqa: PLW0603 — module-level singleton (lazy init); reset only in tests via monkeypatch
    if _client is None:
        _client = AsyncOpenAI(
            api_key=get_settings().openai_api_key or "sk-test",
            timeout=TIMEOUT_S,
        )
    return _client


def _detect_detail_level(image_bytes: bytes, threshold_px: int) -> DetailLevel:
    """Auto-pick OpenAI `detail` param.

    Primary: pyvips (fast, runtime dep — see app/imaging).
    Fallback: Pillow (always available; required so dev envs without
    libvips installed still pick correct detail and don't regress to
    "high" on every call — that would 9x vision cost when cascade
    is enabled, ADR-0004).
    Final fallback (both fail / undecodable bytes): "high" — conservative
    for accuracy.
    """
    w: int | None = None
    h: int | None = None
    try:
        import pyvips  # local import: avoid cold-start cost on import

        img = pyvips.Image.new_from_buffer(image_bytes, "", access="sequential")
        w, h = img.width, img.height
    except Exception:  # noqa: BLE001
        try:
            from PIL import Image as _PILImage

            with _PILImage.open(io.BytesIO(image_bytes)) as _pim:
                w, h = _pim.size
        except Exception:  # noqa: BLE001
            return "high"
    if w is None or h is None:
        return "high"
    if w < threshold_px or h < threshold_px:
        return "low"
    return "high"


def _image_token_estimate(detail: DetailLevel) -> int:
    return IMAGE_TOKEN_LOW if detail == "low" else IMAGE_TOKEN_HIGH


def _should_fallback(items: list[DetectedFoodItem], threshold: float) -> tuple[bool, str]:
    """Return (escalate?, reason). reason ∈ {empty, min_below_threshold,
    low_confidence, ""}."""
    if not items:
        return True, "empty"
    confidences = [i.confidence for i in items]
    min_c = min(confidences)
    if min_c < MIN_ITEM_CONFIDENCE_FLOOR:
        return True, "min_below_threshold"
    avg_c = fmean(confidences)
    if avg_c < threshold:
        return True, "low_confidence"
    return False, ""


@dataclass(slots=True)
class OpenAIVisionProvider:
    """Implements VisionProvider port with hybrid cost cascade."""

    # Optional explicit override (mainly for tests / one-off callsites).
    model: str | None = None

    def _primary_model(self) -> str:
        if self.model is not None:
            return self.model
        s = get_settings()
        # Master cascade flag: when disabled, the "primary" becomes the
        # fallback model (legacy single-call gpt-4o behaviour). Backward
        # compat per QA HIGH-4.
        if not s.vision_cascade_enabled:
            return s.openai_vision_model_fallback or s.openai_vision_model
        return s.openai_vision_model_primary or s.openai_vision_model

    def _fallback_model(self) -> str:
        if self.model is not None:
            return self.model
        s = get_settings()
        return s.openai_vision_model_fallback or s.openai_vision_model

    def current_prompt_sha256(self, *, locale: str, region: str) -> str:
        """Port impl — exposes the prompt-version hash for cache invalidation."""
        return hashlib.sha256(_system_prompt(locale, region).encode()).hexdigest()

    async def is_food_image(
        self,
        *,
        image_bytes: bytes,
        mime: str,
        user_id: UUID | None = None,
    ) -> tuple[bool, str]:
        """Cheap binary food/no-food classifier on gpt-4o-mini detail=low.

        Fail-open contract: any parse/upstream error -> ``(True, ...)`` so the
        full cascade still runs. ``CostCapExceeded`` is intentionally allowed
        to propagate — the daily cap is a hard ceiling that already implies a
        user-facing error response from the upper layers.
        """
        # Cost cap pre-check at the cheapest plausible burn rate. Tiny buffer
        # over the realistic ~$0.0001 so we never block on a single prefilter
        # call once the user is under cap.
        await pre_check(
            user_id=user_id,
            estimate_usd=PREFILTER_COST_ESTIMATE_USD,
        )

        b64 = base64.b64encode(image_bytes).decode()
        data_url = f"data:{mime};base64,{b64}"

        try:
            resp = await _get_client().chat.completions.create(
                model=PREFILTER_MODEL,
                messages=[
                    {"role": "system", "content": PREFILTER_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Clasifica esta imagen."},
                            {"type": "image_url", "image_url": {"url": data_url, "detail": "low"}},
                        ],
                    },
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "food_prefilter",
                        "strict": True,
                        "schema": PREFILTER_SCHEMA,
                    },
                },
                temperature=0.0,
                max_tokens=PREFILTER_MAX_OUTPUT_TOKENS,
            )
            content = resp.choices[0].message.content or "{}"
            usage = resp.usage
            in_tok = getattr(usage, "prompt_tokens", 0) if usage else IMAGE_TOKEN_LOW
            out_tok = (
                getattr(usage, "completion_tokens", 0) if usage else PREFILTER_MAX_OUTPUT_TOKENS
            )
            await record_usage(
                user_id=user_id,
                model=PREFILTER_MODEL,
                in_tok=in_tok,
                out_tok=out_tok,
            )
        except Exception as exc:  # noqa: BLE001 — fail-open by contract
            log.warning(
                "vision.prefilter.upstream_error",
                err=str(exc)[:200],
                user_id=str(user_id) if user_id else None,
            )
            log.info(
                "vision.prefilter.result",
                accept=True,
                reason="upstream_error_accept_default",
                user_id=str(user_id) if user_id else None,
            )
            return True, "upstream_error_accept_default"

        try:
            parsed = json.loads(content)
            accept = bool(parsed["accept"])
            reason_raw = str(parsed["reason"]).strip().lower()
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as je:
            log.warning(
                "vision.prefilter.parse_error",
                err=str(je)[:200],
                content_len=len(content),
                user_id=str(user_id) if user_id else None,
            )
            log.info(
                "vision.prefilter.result",
                accept=True,
                reason="parse_error_accept_default",
                user_id=str(user_id) if user_id else None,
            )
            return True, "parse_error_accept_default"

        reason = reason_raw if reason_raw in PREFILTER_VALID_REASONS else "uncertain"
        log.info(
            "vision.prefilter.result",
            accept=accept,
            reason=reason,
            user_id=str(user_id) if user_id else None,
        )
        return accept, reason

    async def recognise(
        self,
        *,
        image_bytes: bytes,
        mime: str,
        user_id: UUID | None,
        locale: str,
        region: str,
    ) -> tuple[list[DetectedFoodItem], str]:
        s = get_settings()
        sys_prompt = _system_prompt(locale, region)
        prompt_sha = hashlib.sha256(sys_prompt.encode()).hexdigest()

        # MEDIUM-1: Pillow decode is sync CPU-bound — offload to a thread to
        # avoid blocking the event loop on large JPEGs.
        detail: DetailLevel = await asyncio.to_thread(
            _detect_detail_level, image_bytes, s.vision_low_detail_max_dim
        )
        VISION_DETAIL_LEVEL.labels(detail=detail).inc()

        b64 = base64.b64encode(image_bytes).decode()
        data_url = f"data:{mime};base64,{b64}"

        primary_model = self._primary_model()
        fallback_model = self._fallback_model()
        cascade_enabled = primary_model != fallback_model

        # --- Primary call ---
        primary_items = await self._invoke(
            model=primary_model,
            sys_prompt=sys_prompt,
            data_url=data_url,
            detail=detail,
            user_id=user_id,
            max_output_tokens=s.vision_max_output_tokens,
        )

        if not cascade_enabled:
            log.info(
                "vision.cascade",
                primary_model=primary_model,
                fallback_triggered=False,
                cascade_enabled=False,
                n_items=len(primary_items),
                detail=detail,
                prompt_sha=prompt_sha[:8],
            )
            return primary_items, prompt_sha

        escalate, reason = _should_fallback(primary_items, s.vision_confidence_threshold)
        if not escalate:
            VISION_PRIMARY_OK.inc()
            avg_c = fmean(i.confidence for i in primary_items)
            min_c = min(i.confidence for i in primary_items)
            log.info(
                "vision.cascade",
                primary_model=primary_model,
                fallback_triggered=False,
                avg_conf=round(avg_c, 3),
                min_conf=round(min_c, 3),
                n_items=len(primary_items),
                detail=detail,
                prompt_sha=prompt_sha[:8],
            )
            return primary_items, prompt_sha

        # --- Fallback call ---
        VISION_FALLBACK.labels(reason=reason).inc()
        avg_conf_primary = (
            round(fmean(i.confidence for i in primary_items), 3) if primary_items else None
        )
        min_conf_primary = (
            round(min(i.confidence for i in primary_items), 3) if primary_items else None
        )
        log.info(
            "vision.cascade",
            primary_model=primary_model,
            fallback_model=fallback_model,
            fallback_triggered=True,
            reason=reason,
            avg_conf=avg_conf_primary,
            min_conf=min_conf_primary,
            n_items_primary=len(primary_items),
            detail=detail,
            prompt_sha=prompt_sha[:8],
        )
        fallback_items = await self._invoke(
            model=fallback_model,
            sys_prompt=sys_prompt,
            data_url=data_url,
            detail=detail,
            user_id=user_id,
            max_output_tokens=s.vision_max_output_tokens,
        )
        return fallback_items, prompt_sha

    async def _invoke(  # noqa: PLR0913 — keyword-only; args are cohesive call params (model, prompt, image, detail, user, max_tokens).
        self,
        *,
        model: str,
        sys_prompt: str,
        data_url: str,
        detail: DetailLevel,
        user_id: UUID | None,
        max_output_tokens: int,
    ) -> list[DetectedFoodItem]:
        # Cost cap pre-check (CRITICAL-1 fix). Estimate input = prompt tokens
        # + image tokens priced at the ACTUAL model rate, plus a realistic
        # output estimate. Decimal precision throughout (CLAUDE.md #2).
        # Previously hardcoded 2.75/1M and 11.00/1M (gpt-4o full) which
        # overestimated gpt-4o-mini by ~16x and tripped cost-cap prematurely.
        #
        # Output estimate uses 1/4 of max_output_tokens — a realistic typical
        # vision response is 150-300 tokens, far below the truncation ceiling.
        # `record_usage` reconciles to the true value after the call. Using
        # `max_output_tokens` as the ceiling would price every call as if it
        # was a truncation event, throttling legitimate traffic.
        img_tok = _image_token_estimate(detail)
        in_price = _price_input(model)  # USD per 1M input tokens
        out_price = _price_output(model)  # USD per 1M output tokens
        one_m = Decimal(1_000_000)
        text_est_decimal = Decimal(str(estimate_input_cost(model, sys_prompt)))
        image_est = (Decimal(img_tok) / one_m) * in_price
        typical_out_tok = Decimal(max_output_tokens) / Decimal(4)
        out_est = (typical_out_tok / one_m) * out_price
        total_est = text_est_decimal + image_est + out_est
        await pre_check(user_id=user_id, estimate_usd=float(total_est))

        async def _call() -> dict[str, Any]:
            resp = await _get_client().chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Analiza la foto y lista los ítems."},
                            {"type": "image_url", "image_url": {"url": data_url, "detail": detail}},
                        ],
                    },
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
                max_tokens=max_output_tokens,
            )
            content = resp.choices[0].message.content or "{}"
            usage = resp.usage
            await record_usage(
                user_id=user_id,
                model=model,
                in_tok=(getattr(usage, "prompt_tokens", 0) if usage else img_tok),
                out_tok=(getattr(usage, "completion_tokens", 0) if usage else max_output_tokens),
            )
            # HIGH-3: max_tokens truncation can produce incomplete JSON.
            # Treat that as "empty items" so the cascade decision sees no
            # detections and escalates to the fallback model, rather than
            # raising UpstreamError and burning retries on a dead horse.
            try:
                parsed: dict[str, Any] = json.loads(content)
            except json.JSONDecodeError as je:
                VISION_PARSE_ERRORS.labels(model=model).inc()
                log.warning(
                    "vision.invoke.parse_error",
                    model=model,
                    err=str(je)[:200],
                    content_len=len(content),
                )
                parsed = {"items": []}
            return parsed

        attempt = 0
        last_exc: Exception | None = None
        while attempt <= MAX_RETRIES:
            try:
                raw = await _breaker.call(_call)
                items = _parse_items(raw)
                return items
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                attempt += 1
                if attempt > MAX_RETRIES:
                    break
                await asyncio.sleep(0.5 * (2 ** (attempt - 1)))

        log.warning("vision.invoke.failed", model=model, error=str(last_exc))
        raise UpstreamError(f"vision_failed:{last_exc!s}")


def _parse_items(raw: dict[str, Any]) -> list[DetectedFoodItem]:
    out: list[DetectedFoodItem] = []
    for r in raw.get("items", []) or []:
        try:
            out.append(
                DetectedFoodItem(
                    name=str(r["name"])[:120],
                    estimated_amount_g=Decimal(str(r["estimated_amount_g"])),
                    kcal=max(0, int(r["kcal"])),
                    protein_g=max(0, int(r["protein_g"])),
                    carbs_g=max(0, int(r["carbs_g"])),
                    fat_g=max(0, int(r["fat_g"])),
                    confidence=max(0.0, min(1.0, float(r["confidence"]))),
                )
            )
        except (KeyError, ValueError, TypeError, InvalidOperation) as exc:
            # Defensive skip: malformed LLM rows are expected; logged at
            # debug for telemetry, drop the row and continue parsing the
            # remaining items. Narrow surface — any other exception (e.g.
            # AttributeError) signals a real parser bug and must propagate.
            log.debug("vision.parse.skip_row", error=str(exc))
            continue
    return out
