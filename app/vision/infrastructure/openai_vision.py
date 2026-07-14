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
                    "count": {"type": "integer", "minimum": 1},
                    "estimated_amount_g": {"type": "number"},
                    "kcal": {"type": "integer"},
                    "protein_g": {"type": "integer"},
                    "carbs_g": {"type": "integer"},
                    "fat_g": {"type": "integer"},
                    "confidence": {"type": "number"},
                    "food_group": {
                        "type": "string",
                        "enum": [
                            "vegetable",
                            "fruit",
                            "grain",
                            "protein",
                            "dairy",
                            "fat",
                            "sweet",
                            "beverage",
                            "other",
                        ],
                    },
                    "role": {
                        "type": "string",
                        "enum": [
                            "main",
                            "side",
                            "sauce",
                            "condiment",
                            "cooking_fat",
                            "garnish",
                            "sweetener",
                            "beverage_base",
                        ],
                    },
                    "prep_method": {
                        "type": "string",
                        "enum": [
                            "deep_fried",
                            "fried",
                            "sauteed",
                            "grilled",
                            "boiled",
                            "steamed",
                            "baked",
                            "stewed",
                            "raw",
                            "unknown",
                        ],
                    },
                    # BE-5: normalized bounding box (0..1, origin top-left) so
                    # iOS can annotate each item on the photo. null when the
                    # model cannot locate the item (mixed dish / sauce).
                    "bbox": {
                        "type": ["object", "null"],
                        "additionalProperties": False,
                        "properties": {
                            "x": {"type": "number"},
                            "y": {"type": "number"},
                            "w": {"type": "number"},
                            "h": {"type": "number"},
                        },
                        "required": ["x", "y", "w", "h"],
                    },
                },
                "required": [
                    "name",
                    "count",
                    "estimated_amount_g",
                    "kcal",
                    "protein_g",
                    "carbs_g",
                    "fat_g",
                    "confidence",
                    "food_group",
                    "role",
                    "prep_method",
                    "bbox",
                ],
            },
        },
    },
    "required": ["items"],
}


def _system_prompt(
    locale: str,
    region: str,
    plan_context: str | None = None,
    user_profile: dict[str, Any] | None = None,
    portion_history: list[str] | None = None,
) -> str:
    # Plate Decomposition 2.0 — full decomposition, not just visible items.
    # Any wording change here changes prompt_sha256 → SHA dedup cache
    # self-invalidates (by design).
    # plan_context, user_profile, and portion_history are intentionally
    # EXCLUDED from the hash (they are user-specific and change per request;
    # hashing them would defeat the cross-user SHA cache). Injected at call time only.
    base = (
        "Eres un experto en nutrición, planes alimenticios y cocina de LatAm/US/EU. "
        "PROCESO por ítem: (1) identifica el alimento, (2) busca un objeto de referencia "
        "de tamaño conocido en la imagen para anclar la escala, (3) estima el volumen 3D "
        "(área × profundidad), (4) asigna macros basado en peso real estimado.\n"
        "ALCANCE — SOLO la comida servida en el plato/porción que la persona va a "
        "comer. IGNORA por completo (NO son ítems): botellas/frascos de condimentos "
        "sobre la mesa, sachets/sobres sin abrir, posavasos, cubiertos, servilletas, "
        "el fondo, otras porciones o mesas, packaging, y cualquier envase o "
        "condimento que NO esté aplicado sobre la comida. Un condimento cuenta SOLO "
        "si está sobre/dentro del plato (ej. kétchup untado en el pan) — una botella "
        "de kétchup en la mesa NO cuenta. Menos ítems irrelevantes = respuesta más "
        "rápida y precisa.\n"
        "Descompone la COMIDA DEL PLATO — visible e inferido:\n"
        "1) Visibles: principal, guarniciones, salsas/aderezos aplicados, toppings, bebida servida.\n"
        "2) INVISIBLES: aceite en frituras/salteados, mantequilla en purés, "
        "crema en sopas, azúcar en jugos/postres, aderezo en ensaladas aliñadas.\n"
        "3) Especias secas (comino, pimienta, orégano) ≤5 kcal y 1-3 g. "
        "Condimentos calóricos (mayonesa, crema, chimichurri, ketchup) con gramaje real.\n"
        "NO DOBLE-CONTEO (CRÍTICO): cada gramo y cada kcal se cuenta UNA sola vez. "
        "Cuando desglosas un plato compuesto en sus partes (ej. hamburguesa → pan, "
        "carne, queso, tocino, huevo; sándwich → pan + rellenos; taco → tortilla + "
        "relleno), NUNCA agregues además un ítem del plato ENTERO ('hamburguesa "
        "completa', 'sándwich armado'): sus calorías ya están en las partes y "
        "sumarían doble. Elige SIEMPRE el desglose por componentes; el plato entero "
        "como un solo ítem SOLO si NO listaste sus partes.\n"
        "Por ítem (SOLO estos campos, nada más — menos campos = respuesta más rápida): "
        "name, estimated_amount_g, kcal, protein_g, carbs_g, fat_g, confidence (0-1), "
        "food_group (vegetable|fruit|grain|protein|dairy|fat|sweet|beverage|other), "
        "role (main|side|sauce|condiment|cooking_fat|garnish|sweetener|beverage_base), "
        "prep_method (deep_fried|fried|sauteed|grilled|boiled|steamed|baked|stewed|raw|unknown).\n"
        "COHERENCIA: `kcal`≈4·protein_g+4·carbs_g+9·fat_g (Atwater) — que cuadren. "
        "`prep_method` afecta kcal (frito absorbe aceite; a la plancha no). "
        "`confidence`: alto SOLO si identidad "
        "Y tamaño son claros; bajo si ocluido, borroso o dudoso.\n"
        "PORCIONES: si hay mano, moneda, cubierto u otro objeto conocido → úsalo como "
        "calibrador PRINCIPAL. Otras referencias: plato Ø26cm, plato hondo 400ml, "
        "cuchara sopera 15ml, vaso 250ml, taza 240ml, lata 355ml. "
        "Estima profundidad del montículo, no solo área.\n"
        "CONTEO CRÍTICO — LOCALIZA Y CUENTA ANTES DE RESPONDER: para CADA "
        "alimento que pueda venir en unidades repetidas, primero ubica y numera "
        "cada unidad individual una por una (unidad 1, unidad 2, …), incluyendo "
        "las APILADAS, superpuestas o parcialmente ocultas detrás de otra "
        "(ej. dos carnes de hamburguesa una sobre otra, tortas apiladas, huevos, "
        "albóndigas, tacos, panqueques, empanadas, salchichas, rebanadas). "
        "Reporta ese total en `count`=N y `estimated_amount_g`= peso de UNA sola "
        "unidad. NUNCA multipliques tú — la app multiplica. 1 unidad → `count`=1. "
        "Salsas/condimentos/aceites → `count`=1 siempre.\n"
        "DESAMBIGUACIÓN de apilados: ante la duda de si es 1 pieza o 2+ apiladas, "
        "mira el GROSOR (un alto doble = 2 unidades), los BORDES (dos contornos "
        "separados = 2) y las SOMBRAS/líneas horizontales entre capas. Cuenta lo "
        "que la evidencia visual soporta; no asumas 1 por defecto en montículos.\n"
        "IDIOMA DEL NOMBRE: escribe cada `name` en el idioma del Locale — "
        "Locale que empieza con 'en' → nombres en INGLÉS (ej: 'grilled chicken "
        "breast'); cualquier otro → ESPAÑOL (ej: 'pechuga de pollo a la plancha'). "
        "Nombres genéricos y claros, sin marcas.\n"
        "BBOX por ítem `{x,y,w,h}` en fracciones 0-1 de la imagen: `x,y`=esquina "
        "SUPERIOR-IZQUIERDA (no el centro), `w,h`=ancho/alto, con `x+w`≤1 y "
        "`y+h`≤1. Caja ajustada a la extensión visible del alimento; si "
        "`count`>1 cubre el grupo entero. `bbox`:null OBLIGATORIO si no tiene "
        "posición visible clara (inferidos/invisibles: aceite, mantequilla en "
        "puré; salsa mezclada; ingrediente disperso). Nunca inventes coords.\n"
        f"Locale={locale}. Region={region}. JSON estricto, nunca texto libre."
    )
    if user_profile:
        sex = user_profile.get("sex", "")
        age = user_profile.get("age", "")
        weight = user_profile.get("weight_kg", "")
        base += (
            f"\nPERFIL DEL USUARIO: {sex}, {age} años, {weight}kg. "
            "Calibra las porciones típicas para este perfil — una persona más grande "
            "generalmente sirve porciones más grandes."
        )
    if plan_context:
        base += (
            f"\nCONTEXTO DEL PLAN: El usuario planificó comer: {plan_context}. "
            "Úsalo como referencia para calibrar porciones — si ves los mismos "
            "ingredientes, estima qué fracción del plan está en el plato. "
            "No inventes ítems que no estén visibles."
        )
    if portion_history:
        anchors = ", ".join(portion_history)
        base += (
            f"\nHISTORIAL DE PORCIONES: Este usuario suele servirse: {anchors}. "
            "Si reconoces los mismos alimentos, ajusta el gramaje estimado al patrón "
            "histórico de este usuario."
        )
    return base


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


_DARK_BRIGHTNESS_THRESHOLD = 80  # mean RGB < 80/255 → enhance


def _enhance_if_dark(image_bytes: bytes, mime: str) -> tuple[bytes, str]:
    """Apply autocontrast to dark food photos before sending to the VLM.

    Dark images cause the model to underestimate portion sizes and miss
    low-contrast items (sauces, garnishes). This raises overall confidence
    without touching API pricing (local CPU-only operation).

    Returns (possibly_enhanced_bytes, corrected_mime). On any error returns
    the originals unchanged — enhancement is purely best-effort.
    """
    try:
        from PIL import Image as _PILImage  # noqa: PLC0415
        from PIL import ImageEnhance, ImageOps, ImageStat

        with _PILImage.open(io.BytesIO(image_bytes)) as img:
            rgb = img.convert("RGB")
            mean_brightness = sum(ImageStat.Stat(rgb).mean) / 3
            if mean_brightness >= _DARK_BRIGHTNESS_THRESHOLD:
                return image_bytes, mime
            # Clip 1% extremes + stretch histogram, then mild contrast boost.
            enhanced = ImageOps.autocontrast(rgb, cutoff=1)
            enhanced = ImageEnhance.Contrast(enhanced).enhance(1.25)
            out = io.BytesIO()
            enhanced.save(out, format="JPEG", quality=85)
            log.debug(
                "vision.enhance.applied",
                original_mime=mime,
                mean_brightness=round(mean_brightness, 1),
            )
            return out.getvalue(), "image/jpeg"
    except Exception:  # noqa: BLE001 — OK4: enhancement is best-effort; originals returned on any error
        return image_bytes, mime


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


def _model_is_gpt5_family(model: str) -> bool:
    """GPT-5 and the o-series reasoning models reject legacy call params."""
    m = model.lower()
    return m.startswith(("gpt-5", "o1", "o3", "o4"))


def _completion_kwargs(model: str, max_output_tokens: int) -> dict[str, Any]:
    """Model-family-correct completion params for `chat.completions.create`.

    GPT-5 / o-series reject `max_tokens` (require `max_completion_tokens`) and
    reject any `temperature` other than the default 1. Older models (gpt-4o*)
    still take `max_tokens` + `temperature=0.0` (kept for deterministic output).

    For GPT-5 we pin `reasoning_effort="low"` (measured 2026-07-11 against the
    real vision prompt): `minimal` starves the model — it can't work through
    the dense decomposition/count/portion instructions and bails to an EMPTY
    `items` list; `medium` also returned empty (over-reasons/truncates). `low`
    detected reliably ([10,10,9,10] items on the same image). `max_completion_
    tokens` is SHARED with reasoning tokens, so the caller MUST size it well
    above the raw output (~1800 tok) plus reasoning (~500-960 tok) — see
    `vision_max_output_tokens` (4000). Sent via `extra_body` so it passes
    through regardless of the SDK version's typed params.
    """
    if _model_is_gpt5_family(model):
        s = get_settings()
        return {
            "max_completion_tokens": max_output_tokens,
            # verbosity="low" ~= 30% fewer output tokens than the default
            # "medium" → faster response, correct for an extraction task.
            # Both env-overridable (see config) for latency experiments.
            "extra_body": {
                "reasoning_effort": s.vision_reasoning_effort,
                "verbosity": s.vision_verbosity,
            },
        }
    return {"max_tokens": max_output_tokens, "temperature": 0.0}


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
                **_completion_kwargs(PREFILTER_MODEL, PREFILTER_MAX_OUTPUT_TOKENS),
            )
            content = resp.choices[0].message.content or "{}"
            usage = resp.usage
            in_tok = getattr(usage, "prompt_tokens", 0) if usage else IMAGE_TOKEN_LOW
            out_tok = (
                getattr(usage, "completion_tokens", 0) if usage else PREFILTER_MAX_OUTPUT_TOKENS
            )
            cached_tok = 0
            if usage and hasattr(usage, "prompt_tokens_details") and usage.prompt_tokens_details:
                cached_tok = getattr(usage.prompt_tokens_details, "cached_tokens", 0) or 0
            await record_usage(
                user_id=user_id,
                model=PREFILTER_MODEL,
                in_tok=in_tok,
                out_tok=out_tok,
                cached_tok=cached_tok,
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

        if reason_raw not in PREFILTER_VALID_REASONS:
            # Surface the raw value: if a prompt update makes the LLM emit
            # new reason codes, this is the only trace of what it said.
            log.info("vision.prefilter.invalid_reason", reason_raw=str(reason_raw)[:60])
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
        stage: str = "auto",
        plan_context: str | None = None,
        user_profile: dict[str, Any] | None = None,
        portion_history: list[str] | None = None,
    ) -> tuple[list[DetectedFoodItem], str]:
        s = get_settings()
        # prompt_sha uses only stable parts (locale, region) — plan_context,
        # user_profile, and portion_history are per-user and must not enter
        # the cross-user cache key.
        prompt_sha = hashlib.sha256(_system_prompt(locale, region).encode()).hexdigest()
        sys_prompt = _system_prompt(
            locale,
            region,
            plan_context=plan_context,
            user_profile=user_profile,
            portion_history=portion_history,
        )

        # Enhance dark food photos before sending to the VLM (best-effort,
        # local CPU — zero API cost). Run in thread: PIL is sync CPU-bound.
        image_bytes, mime = await asyncio.to_thread(_enhance_if_dark, image_bytes, mime)

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

        # Pipeline-directed stages (grounded escalation, 2026-06-11):
        # the use case calls "primary_only" first, grounds the result
        # against the foods catalog, and only re-calls with "full_only"
        # when grounding could NOT vouch for the cheap model's output.
        # This kills the escalations the old internal cascade fired for
        # photos whose macros the catalog fixes anyway.
        if stage == "full_only":
            full_items = await self._invoke(
                model=fallback_model,
                sys_prompt=sys_prompt,
                data_url=data_url,
                detail=detail,
                user_id=user_id,
                max_output_tokens=s.vision_max_output_tokens,
            )
            log.info(
                "vision.cascade",
                stage=stage,
                fallback_model=fallback_model,
                n_items=len(full_items),
                detail=detail,
                prompt_sha=prompt_sha[:8],
            )
            return full_items, prompt_sha

        # --- Primary call ---
        primary_items = await self._invoke(
            model=primary_model,
            sys_prompt=sys_prompt,
            data_url=data_url,
            detail=detail,
            user_id=user_id,
            max_output_tokens=s.vision_max_output_tokens,
        )

        if stage == "primary_only":
            if not cascade_enabled:
                # Misconfig guard: primary == fallback means this call
                # already paid the heavy model; a pipeline escalation to
                # "full_only" would pay it AGAIN for the same answer.
                log.warning(
                    "vision.cascade.models_identical",
                    model=primary_model,
                    hint="set distinct openai_vision_model_primary/fallback or disable cascade",
                )
            log.info(
                "vision.cascade",
                stage=stage,
                primary_model=primary_model,
                n_items=len(primary_items),
                detail=detail,
                prompt_sha=prompt_sha[:8],
            )
            return primary_items, prompt_sha

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
                **_completion_kwargs(model, max_output_tokens),
            )
            content = resp.choices[0].message.content or "{}"
            usage = resp.usage
            _cached_tok = 0
            if usage and hasattr(usage, "prompt_tokens_details") and usage.prompt_tokens_details:
                _cached_tok = getattr(usage.prompt_tokens_details, "cached_tokens", 0) or 0
            await record_usage(
                user_id=user_id,
                model=model,
                in_tok=(getattr(usage, "prompt_tokens", 0) if usage else img_tok),
                out_tok=(getattr(usage, "completion_tokens", 0) if usage else max_output_tokens),
                cached_tok=_cached_tok,
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


_FOOD_GROUPS: frozenset[str] = frozenset(
    {"vegetable", "fruit", "grain", "protein", "dairy", "fat", "sweet", "beverage", "other"}
)

# Plate Decomposition 2.0 vocab — kept in sync with VISION_SCHEMA enums and
# app/vision/domain/plate_decomposition.py.
_ITEM_ROLES: frozenset[str] = frozenset(
    {"main", "side", "sauce", "condiment", "cooking_fat", "garnish", "sweetener", "beverage_base"}
)
_PREP_METHODS: frozenset[str] = frozenset(
    {
        "deep_fried",
        "fried",
        "sauteed",
        "grilled",
        "boiled",
        "steamed",
        "baked",
        "stewed",
        "raw",
        "unknown",
    }
)

# Atwater: if |llm_kcal - macro_kcal| / max(both) > threshold, trust macros.
# 15% is tight enough to catch arithmetic errors while allowing rounding noise.
_ATWATER_THRESHOLD = 0.15

# USDA oil absorption coefficients by prep method.
# Source: USDA FDC fat retention studies (deep-fry 8-15%, pan-fry 3-7%, sauté 1-5%).
_OIL_ABSORPTION_PCT: dict[str, float] = {
    "deep_fried": 0.11,
    "fried": 0.05,
    "sauteed": 0.03,
}
_OIL_KCAL_PER_G = 9  # fat = 9 kcal/g (Atwater)


def _atwater_correct(
    kcal_llm: int,
    protein_g: int,
    carbs_g: int,
    fat_g: int,
) -> tuple[int, bool]:
    """Return (best_kcal, was_corrected).

    If macros sum to zero (water, pure spices) trust LLM kcal as-is.
    Otherwise use Atwater (4/4/9) when discrepancy exceeds threshold.
    """
    macro_kcal = protein_g * 4 + carbs_g * 4 + fat_g * 9
    if macro_kcal == 0:
        return kcal_llm, False
    if kcal_llm == 0:
        return macro_kcal, True
    discrepancy = abs(kcal_llm - macro_kcal) / max(kcal_llm, macro_kcal)
    if discrepancy > _ATWATER_THRESHOLD:
        return macro_kcal, True
    return kcal_llm, False


def _hidden_calorie_post_pass(items: list[DetectedFoodItem]) -> list[DetectedFoodItem]:
    """Inject inferred cooking-fat item for fried/sauteed foods.

    Skips if LLM already detected a cooking_fat role item — no double-counting.
    Aggregates absorbed oil across all fried items into one inferred entry.
    Absorption uncertainty: -20% / +40% (asymmetric — easier to absorb more).
    """
    if any(i.role == "cooking_fat" for i in items):
        return items

    total_oil_g = 0.0
    for item in items:
        pct = _OIL_ABSORPTION_PCT.get(item.prep_method or "")
        if pct is None:
            continue
        amount_g = float(item.estimated_amount_g)
        if amount_g <= 0:
            continue
        total_oil_g += amount_g * pct

    if total_oil_g < 1.0:
        return items

    oil_g = round(total_oil_g)
    oil_kcal = round(total_oil_g * _OIL_KCAL_PER_G)
    oil_kcal_min = round(total_oil_g * 0.8 * _OIL_KCAL_PER_G)
    oil_kcal_max = round(total_oil_g * 1.4 * _OIL_KCAL_PER_G)

    log.info(
        "vision.hidden_calorie.cooking_fat_injected",
        oil_g=oil_g,
        oil_kcal=oil_kcal,
    )

    inferred = DetectedFoodItem(
        name="Aceite de cocción (inferido)",
        estimated_amount_g=Decimal(str(oil_g)),
        kcal=oil_kcal,
        kcal_min=oil_kcal_min,
        kcal_max=oil_kcal_max,
        protein_g=0,
        carbs_g=0,
        fat_g=oil_g,
        fiber_g=0,
        sugar_g=0,
        confidence=0.7,
        food_group="fat",
        role="cooking_fat",
        prep_method=None,
        inferred=True,
    )
    return [*items, inferred]


def _parse_items(raw: dict[str, Any]) -> list[DetectedFoodItem]:
    out: list[DetectedFoodItem] = []
    for r in raw.get("items", []) or []:
        try:
            group = str(r.get("food_group", "other"))
            role = str(r.get("role") or "") or None
            prep = str(r.get("prep_method") or "") or None

            # count: number of identical visible units (2 patties, 3 pancakes…).
            # LLM returns per-unit amounts; we multiply deterministically here
            # so the rest of the pipeline always works with totals.
            count = max(1, int(r.get("count") or 1))

            protein_g = max(0, int(r["protein_g"])) * count
            carbs_g = max(0, int(r["carbs_g"])) * count
            fat_g = max(0, int(r["fat_g"])) * count
            kcal_raw = max(0, int(r["kcal"])) * count
            amount_g = float(r["estimated_amount_g"]) * count

            kcal_best, corrected = _atwater_correct(kcal_raw, protein_g, carbs_g, fat_g)
            if corrected:
                log.info(
                    "vision.parse.atwater_correction",
                    name=str(r.get("name", "?"))[:60],
                    kcal_llm=kcal_raw,
                    kcal_atwater=kcal_best,
                    count=count,
                )
            if count > 1:
                log.info(
                    "vision.parse.count_multiplied",
                    name=str(r.get("name", "?"))[:60],
                    count=count,
                    amount_g_per_unit=float(r["estimated_amount_g"]),
                    amount_g_total=amount_g,
                )

            # kcal_min/max: widen range to encompass both LLM estimate and
            # Atwater correction so uncertainty is honestly represented.
            kcal_min_raw = r.get("kcal_min")
            kcal_max_raw = r.get("kcal_max")
            kcal_min: int | None = None
            kcal_max: int | None = None
            if kcal_min_raw is not None:
                kcal_min = min(max(0, int(kcal_min_raw)) * count, kcal_best, kcal_raw)
            if kcal_max_raw is not None:
                kcal_max = max(int(kcal_max_raw) * count, kcal_best, kcal_raw)

            # BE-5: normalized bounding box. Accept only a complete, in-range,
            # in-bounds box: each of x,y,w,h in [0,1], positive size, and the
            # box must not exceed the image (x+w<=1, y+h<=1, small epsilon for
            # rounding). Anything else → None (never fabricate a position).
            bbox: tuple[float, float, float, float] | None = None
            bbox_raw = r.get("bbox")
            if isinstance(bbox_raw, dict):
                try:
                    bx, by, bw, bh = (float(bbox_raw[k]) for k in ("x", "y", "w", "h"))
                    _eps = 0.01
                    if (
                        all(0.0 <= v <= 1.0 for v in (bx, by, bw, bh))
                        and bw > 0.0
                        and bh > 0.0
                        and bx + bw <= 1.0 + _eps
                        and by + bh <= 1.0 + _eps
                    ):
                        bbox = (bx, by, bw, bh)
                except (KeyError, TypeError, ValueError):
                    bbox = None

            out.append(
                DetectedFoodItem(
                    name=str(r["name"])[:120],
                    estimated_amount_g=Decimal(str(amount_g)),
                    kcal=kcal_best,
                    protein_g=protein_g,
                    carbs_g=carbs_g,
                    fat_g=fat_g,
                    # fiber_g/sugar_g: new in schema v3; old cached rows return 0 (safe default).
                    fiber_g=max(0, int(r.get("fiber_g") or 0)) * count,
                    sugar_g=max(0, int(r.get("sugar_g") or 0)) * count,
                    confidence=max(0.0, min(1.0, float(r["confidence"]))),
                    food_group=group if group in _FOOD_GROUPS else "other",  # type: ignore[arg-type]
                    role=role if role in _ITEM_ROLES else None,
                    prep_method=prep if prep in _PREP_METHODS else None,
                    kcal_min=kcal_min,
                    kcal_max=kcal_max,
                    count=count,
                    bbox=bbox,
                )
            )
        except (KeyError, ValueError, TypeError, InvalidOperation) as exc:
            # Defensive skip: malformed LLM rows are expected; drop the row
            # and continue parsing the remaining items. INFO (not debug):
            # a silently dropped row means the user's detected-items count
            # won't match their plate — ops needs to see how often.
            # Narrow surface — any other exception (e.g. AttributeError)
            # signals a real parser bug and must propagate.
            log.info(
                "vision.parse.skip_row",
                error=str(exc),
                name=str(r.get("name", "?"))[:60],
            )
            continue
    return _hidden_calorie_post_pass(out)
