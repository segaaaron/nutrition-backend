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
import re as _re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from dataclasses import replace as _dc_replace
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
from app.vision.domain.entities import DetectedFoodItem, FoodGroup
from app.vision.domain.plate_decomposition import (
    OIL_ABSORPTION_PCT,
    OIL_KCAL_PER_G,
    cap_implausible_portions,
)
from app.vision.domain.value_objects import FoodIdentification, PortionEstimate, PortionHint

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

# ---------------------------------------------------------------------------
# Per-user context hint injected into the vision system prompt (2026-07-25).
# ---------------------------------------------------------------------------

@dataclass(slots=True, frozen=True)
class UserVisionContext:
    """Caller-provided per-user signals that sharpen the vision system prompt.

    ``region``: ISO-3166-1 alpha-2 country code or full country name
    (e.g. ``"BO"``, ``"MX"``).  Used to detect landlocked regions whose
    users never have ocean seafood on their plates.

    ``meal_time``: one of ``breakfast/lunch/dinner/snack``.  Drives per-slot
    portion-size expectations in the prompt.

    ``portion_history``: ordered tuple of ``"food_name Xg"`` strings (highest
    correction frequency first) from ``vision_user_corrections``.  The top-3
    entries are surfaced to the model as identification anchors.
    """

    region: str
    meal_time: str | None = None
    portion_history: tuple[str, ...] | None = None


# Countries in LATAM without ocean coastline — these users cannot have
# ocean fish/shellfish on their plates.  Matched case-insensitively against
# region ISO codes or full names passed by the caller.
#
# GAP (2026-07-25): The system currently passes region="latam" as the canonical
# value for all LATAM users rather than a per-country code. This means the
# landlocked check NEVER fires for BO/PARAGUAY users because their profile
# country is not mapped to a region code before this check.
# The correct fix is to map profile.country → ISO-3166-1 alpha-2 in the
# process_vision_job pipeline BEFORE building UserVisionContext, then pass
# the per-country code as `region`. Do NOT add "latam" here: LATAM includes
# major seafood consumers (Peru, Chile, Brazil, Argentina, Mexico, Colombia,
# Ecuador) — treating the whole region as landlocked would wrongly suppress
# ocean seafood identification for the vast majority of LATAM users.
# Owner decision required before any region mapping is implemented.
_LANDLOCKED_LATAM_REGIONS: frozenset[str] = frozenset(
    {"BO", "BOLIVIA", "PY", "PARAGUAY"}
)


def _build_user_context_hint(ctx: UserVisionContext) -> str:
    """Generate additional context to append to the vision system prompt.

    Returns an empty string when no useful signals are present so the caller
    can skip the append with a simple truthiness check.  Pure function —
    no I/O, no state.

    Signals handled:
    - Landlocked LATAM region → instruct model to never identify ocean seafood.
    - Snack slot → emphasise per-item small-portion expectations beyond the
      kcal-range hint already in the base prompt.
    - User correction history → surface top-3 frequent foods as recognition
      anchors (complements the gramaje anchors in portion_history, focusing
      on IDENTITY rather than amount).
    """
    parts: list[str] = []

    region_key = (ctx.region or "").upper().strip()
    if region_key in _LANDLOCKED_LATAM_REGIONS:
        parts.append(
            "REGIÓN SIN COSTA MARÍTIMA: este usuario NO consume camarones, "
            "langostinos, langosta, cangrejo, pulpo, calamar ni ningún otro "
            "marisco de mar. Cuando detectes una proteína acuática, identificala "
            "como trucha, tilapia, surubí, pacú u otro pez de río o lago — "
            "NUNCA como marisco de mar."
        )

    if ctx.meal_time == "snack":
        parts.append(
            "SLOT SNACK — PORCIONES PEQUEÑAS POR ÍTEM: fruta 1 pieza (≤150 g), "
            "yogur ≤180 g, queso ≤30 g, nueces ≤25 g, galletitas ≤5 unidades "
            "(≤50 g total), proteína cocida ≤120 g. Si algún ítem supera estas "
            "referencias en un snack, revisá si el gramaje es correcto y reducilo."
        )

    if ctx.portion_history:
        top3 = ", ".join(ctx.portion_history[:3])
        parts.append(
            f"ALIMENTOS HABITUALES DE ESTE USUARIO (por frecuencia de corrección): "
            f"{top3}. Si alguno aparece en la imagen, prioriza esa identificación y "
            f"calibra el gramaje a su patrón histórico."
        )

    return "\n".join(parts)


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
        # Declared FIRST on purpose: strict constrained-decoding emits properties
        # in declaration order, so the model must write this unit-count scratchpad
        # BEFORE `items` — a forced chain-of-thought that makes it enumerate every
        # repeated/stacked unit (per-food, e.g. "carne: u1+u2=2; pan:2") before it
        # commits each `count`. Generic: applies to any food, not one dish. Ignored
        # by the parser (_parse_items reads only `items`); it exists to steer the
        # weaker vision model away from lumping composites into one unit.
        "unit_census": {"type": "string"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    # Declared BEFORE `count` on purpose: constrained decoding
                    # generates properties in order, so the model must CLASSIFY
                    # whole-piece vs bulk BEFORE it picks count. This anchors the
                    # count (weak models over-count chunks of a pile otherwise).
                    # The field NAME + enum act as the instruction channel;
                    # `_parse_items` also hard-clamps count=1 when 'a_granel', so
                    # correctness holds even if the model disobeys.
                    "portion_kind": {"type": "string", "enum": ["pieza_entera", "a_granel"]},
                    "count": {"type": "integer", "minimum": 1},
                    "size_category": {"type": "string", "enum": ["XS", "S", "M", "L", "XL"]},
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
                    "portion_kind",
                    "count",
                    "size_category",
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
    "required": ["unit_census", "items"],
}


def _system_prompt(
    locale: str,
    region: str,
    plan_context: str | None = None,
    user_profile: dict[str, Any] | None = None,
    portion_history: list[str] | None = None,
    user_context: str | None = None,
    meal_time: str | None = None,
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
        "DESGLOSE OBLIGATORIO: todo alimento armado cuyas partes se distingan DEBE "
        "listarse por COMPONENTES separados, nunca como un ítem con el nombre del "
        "conjunto (ej. hamburguesa → pan + carne(s) + queso + toppings; taco → "
        "tortilla + relleno). Son ejemplos, no lista cerrada: aplica el principio a "
        "cualquier plato armado. PROHIBIDO el conjunto como ítem único cuando sus "
        "partes se ven — ya están contadas en las partes. Plato como UN ítem SÓLO "
        "si sus partes son indistinguibles/homogéneas (sopa licuada, batido, "
        "puré).\n"
        "Por ítem (SOLO estos campos, nada más — menos campos = respuesta más rápida): "
        "name, estimated_amount_g, size_category, kcal, protein_g, carbs_g, fat_g, "
        "confidence (0-1), "
        "food_group (vegetable|fruit|grain|protein|dairy|fat|sweet|beverage|other), "
        "role (main|side|sauce|condiment|cooking_fat|garnish|sweetener|beverage_base), "
        "prep_method (deep_fried|fried|sauteed|grilled|boiled|steamed|baked|stewed|raw|unknown).\n"
        "CAMPO CRÍTICO `size_category` — OBLIGATORIO en TODOS los ítems: "
        "XS=muy pequeño (mitad de porción chica), S=pequeño, M=porción normal hogar 1 adulto, "
        "L=grande, XL=muy grande. "
        "MÉTODO: (1) detecta objeto de referencia visible (tenedor≈18cm, cuchara sopera≈15cm, "
        "plato estándar≈26cm Ø, mano adulta≈18cm, moneda 25mm). "
        "(2) Compara el alimento con esa referencia para juzgar el tamaño VISUAL. "
        "(3) Asigna XS/S/M/L/XL ANTES de escribir estimated_amount_g. "
        "(4) estimated_amount_g debe ser COHERENTE con size_category "
        "(ej. pollo M → 120-140g, arroz M → 140-160g, NO pongas M y 40g — se contradicen).\n"
        "COHERENCIA: `kcal`≈4·protein_g+4·carbs_g+9·fat_g (Atwater) — que cuadren. "
        "`prep_method` afecta kcal (frito absorbe aceite; a la plancha no). "
        "`confidence`: alto SOLO si identidad "
        "Y tamaño son claros; bajo si ocluido, borroso o dudoso.\n"
        "PORCIONES — calibración HOGAR LATAM (no restaurante): si hay mano, moneda, "
        "cubierto u otro objeto conocido → úsalo como calibrador PRINCIPAL. "
        "Otras referencias: plato Ø26cm, plato hondo 400ml, "
        "cuchara sopera 15ml, vaso 250ml, taza 240ml, lata 355ml. "
        "Estima profundidad del montículo, no solo área. "
        "ANCLAS DE PORCIÓN INDIVIDUAL (cocina de hogar LATAM, UNA persona): "
        "proteína (filete/pechuga/lomo) 120-200g; filete de pescado 130-200g; "
        "carne molida/guisada 100-180g; "
        "arroz cocido 120-200g; pasta cocida 150-220g; papas cocidas 100-180g; "
        "legumbres cocidas 80-150g; masa de pizza (pizza personal entera) 120-170g; "
        "queso en pizza 60-90g; verdura cocida por tipo 60-130g; ensalada mixta 80-150g; "
        "pan/tostada (rebanada) 30-50g; fruta mediana entera 120-180g. "
        "RANGOS CALÓRICOS ESPERADOS por comida (hogar individual): "
        "desayuno 300-550 kcal; almuerzo 500-750 kcal; cena 400-650 kcal; snack 80-220 kcal. "
        "⚠️ VERIFICACIÓN FINAL OBLIGATORIA: suma todos tus ítems. "
        "Si el total supera el rango esperado para esa comida, "
        "REVISÁ las porciones MÁS GRANDES y ajustá a la baja antes de responder. "
        "El error más común es SOBREESTIMAR el gramaje — un plato parece grande visualmente "
        "pero la porción real es moderada. Ante la duda, estimá hacia la porción MEDIANA del rango. "
        "EXCEPCIÓN — ALIMENTOS LICUADOS/MEZCLADOS (batido, smoothie, licuado, gachas, porridge, "
        "sémola, crema, potaje, puré): contienen ingredientes densos INVISIBLES en el blend "
        "(aguacate, plátano, leche entera, mantequilla de maní, miel, semillas, crema). "
        "Densidad de referencia: batido de frutas con lácteos 70-90 kcal/100ml; "
        "batido con aguacate/nuez/coco 100-130 kcal/100ml; "
        "gachas/porridge con leche 90-120 kcal/100g. "
        "Si tu estimado es MÁS BAJO que estos rangos para una porción visible de tamaño normal, "
        "AÑADÍ los ingredientes densos más probables (leche entera, aguacate, miel) como ítems "
        "invisibles separados antes de finalizar.\n"
        "PROTEÍNA FALTANTE — DOBLE VERIFICACIÓN: en platos de almuerzo/cena, "
        "antes de finalizar verificá que hayas incluido la proteína principal "
        "(carne, pollo, pescado, mariscos, huevo, legumbre). Si no ves ninguna, "
        "REVISÁ la imagen — puede estar bajo salsa, semioculta, con color similar "
        "al plato, o en el borde. Un plato principal sin proteína es inusual.\n"
        "SOPAS/CREMAS CON SÓLIDOS: si el plato base es sopa o crema pero hay "
        "ingredientes sólidos VISIBLES (trozos de carne, papa, verdura entera, "
        "legumbre), listalós POR SEPARADO además de la base líquida. No los "
        "absorba en 'sopa cremosa general' — la base líquida es UN ítem, cada "
        "sólido identificable es otro ítem adicional.\n"
        "SNACK CON MÚLTIPLES INGREDIENTES: en snacks con 2-4 componentes "
        "(frutas + nueces, queso + crackers, yogur + granola), verificá que "
        "TODOS estén listados. Nueces, frutos secos y frutos rojos son "
        "pequeños y fáciles de omitir aunque estén claramente presentes.\n"
        "CONTEO CRÍTICO — LOCALIZA Y CUENTA ANTES DE RESPONDER: para CADA "
        "alimento que venga en piezas enteras repetidas, primero ubica y numera "
        "cada unidad una por una (unidad 1, unidad 2, …), incluyendo las APILADAS, "
        "superpuestas u ocultas detrás de otra (ej. dos carnes de hamburguesa "
        "apiladas, panqueques, empanadas, salchichas). "
        "Reporta ese total en `count`=N y `estimated_amount_g`= peso de UNA sola "
        "unidad. NUNCA multipliques tú — la app multiplica.\n"
        "CLASIFICA cada ítem con `portion_kind` ANTES de `count`: "
        "`pieza_entera` = piezas enteras idénticas que levantarías de a una con "
        "tenedor (carnes de burger, panqueques, huevos, empanadas) → `count` = "
        "cuántas hay. `a_granel` = picado/en trozos/rodajas o aros sueltos/guiso/"
        "montón (carne salteada, papas fritas, cebolla en aros) y salsas/aceites → "
        "`count`=1, `estimated_amount_g` = peso TOTAL del montón. Pan base+tapa = "
        "`pieza_entera`, `count`=1.\n"
        "DESAMBIGUACIÓN de apilados: ante duda 1 vs 2+, mira GROSOR (alto doble=2), "
        "BORDES (dos contornos=2) y SOMBRAS entre capas. No asumas 1 por defecto.\n"
        "CENSO (`unit_census`, OBLIGATORIO, va ANTES de `items`): UNA línea breve "
        "con las PIEZAS ENTERAS repetidas — ej. 'carne:2; queso:2; huevo:1'. Copia "
        "al `count` de cada `pieza_entera`. Sé breve.\n"
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
    if meal_time:
        _meal_kcal = {
            "breakfast": "300-550 kcal",
            "lunch": "500-750 kcal",
            "dinner": "400-650 kcal",
            "snack": "80-220 kcal",
        }
        kcal_hint = _meal_kcal.get(meal_time, "")
        base += (
            f"\nCOMIDA DEL DÍA: {meal_time}."
            + (f" Rango calórico esperado: {kcal_hint}." if kcal_hint else "")
            + " Si tu suma excede este rango, ajustá las porciones mayores a la baja."
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
    if user_context:
        # Free-text note the user attached to THIS photo (e.g. "plato familiar
        # para compartir", "es individual", "porción de niño"). Portion size is
        # the single biggest error source, so this per-photo cue is the strongest
        # calibration signal — weigh it above generic priors. It only calibrates
        # AMOUNTS; never let it invent items that aren't visible.
        base += (
            f"\nCONTEXTO DE ESTA FOTO (dicho por el usuario): «{user_context}». "
            "Es la señal MÁS FUERTE para calibrar el TAMAÑO de las porciones — "
            "priorízala sobre supuestos genéricos (ej. 'para compartir'/'familiar' "
            "→ subí el gramaje; 'individual'/'de niño' → bajalo). Úsalo SOLO para el "
            "gramaje; nunca agregues alimentos que no se vean en la imagen."
        )
    # Per-user context hint: landlocked region, slot-specific size anchors,
    # user's most-corrected foods.  Build from the caller-provided signals;
    # returns "" when nothing useful is available.
    user_ctx_hint = _build_user_context_hint(
        UserVisionContext(
            region=region,
            meal_time=meal_time,
            portion_history=tuple(portion_history) if portion_history else None,
        )
    )
    if user_ctx_hint:
        base += f"\n{user_ctx_hint}"
    return base


# ---------------------------------------------------------------------------
# Two-pass schemas and prompts (identify + estimate)
# ---------------------------------------------------------------------------

IDENTIFY_SCHEMA: dict[str, Any] = {
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
                    "confidence": {"type": "number"},
                    "group": {
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
                            "grilled",
                            "fried",
                            "deep_fried",
                            "boiled",
                            "raw",
                            "baked",
                            "sauteed",
                            "steamed",
                            "stewed",
                            "unknown",
                        ],
                    },
                    "count": {"type": "integer", "minimum": 1},
                    "portion_kind": {
                        "type": "string",
                        "enum": ["pieza_entera", "a_granel"],
                    },
                },
                "required": [
                    "name",
                    "confidence",
                    "group",
                    "role",
                    "prep_method",
                    "count",
                    "portion_kind",
                ],
            },
        }
    },
    "required": ["items"],
}

ESTIMATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "estimates": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "index": {"type": "integer", "minimum": 0},
                    "estimated_amount_g": {"type": "number"},
                    "kcal": {"type": "integer"},
                    "protein_g": {"type": "integer"},
                    "carbs_g": {"type": "integer"},
                    "fat_g": {"type": "integer"},
                    "confidence": {"type": "number"},
                },
                "required": [
                    "index",
                    "estimated_amount_g",
                    "kcal",
                    "protein_g",
                    "carbs_g",
                    "fat_g",
                    "confidence",
                ],
            },
        }
    },
    "required": ["estimates"],
}


def _identify_system_prompt(locale: str, region: str) -> str:
    """Identification-only prompt for Call 1 of the two-pass pipeline.

    Full detection power — NO grams or macros (that is Call 2's job).
    Any wording change here changes identification_prompt_sha256 → cache invalidation.
    """
    return (
        "Eres un experto en nutrición y cocina de LatAm/US/EU. "
        "Analiza la imagen e IDENTIFICA todos los alimentos. "
        "NO estimes gramos, kcal ni macros — solo identificación exhaustiva.\n"
        "ALCANCE — SOLO la comida servida que la persona va a comer. "
        "IGNORA: botellas/frascos de condimentos en la mesa, sachets sin abrir, "
        "cubiertos, servilletas, packaging, otras porciones de otras personas. "
        "Un condimento cuenta SOLO si está aplicado sobre/dentro del plato.\n"
        "DESGLOSE — DOS CASOS DISTINTOS:\n"
        "CASO 1 — PLATO ARMADO EN CAPAS/SECCIONES: listá cada componente separado. "
        "Ejemplos: hamburguesa → pan + carne + queso + toppings; "
        "taco/burrito → tortilla + relleno + salsa; sandwich → pan + proteína + aderezos; "
        "plato con proteína + guarnición + ensalada en secciones visibles → 3 ítems. "
        "La clave: componentes APILADOS, ENSAMBLADOS o en SECCIONES FÍSICAMENTE SEPARADAS.\n"
        "CASO 2 — PREPARACIÓN COCINADA INTEGRADA: listá como UN solo ítem con nombre del plato. "
        "Ejemplos: arroz con pollo, fideos salteados, guiso de lentejas, paella, locro, "
        "sopa con ingredientes mezclados, pasta con salsa integrada, revuelto de huevo. "
        "La clave: ingredientes MEZCLADOS O COCIDOS JUNTOS y no separables visualmente.\n"
        "CASO 2 + PROTEÍNA VISIBLE APARTE: si el guiso tiene proteína ENTERA aparte "
        "(ej. muslo de pollo encima del arroz, huevo frito sobre fideos), esa pieza SÍ es ítem separado.\n"
        "ÍTEMS INVISIBLES A INCLUIR SIEMPRE:\n"
        "- Aceite en frituras y salteados (cooking_fat).\n"
        "- Mantequilla en purés, panqueques, tostadas con mantequilla.\n"
        "- Crema/leche en sopas cremosas.\n"
        "- Aderezo en ensaladas aliñadas.\n"
        "- Azúcar en jugos de fruta, postres, avena con azúcar.\n"
        "NO DOBLE-CONTEO: cada alimento se lista UNA sola vez.\n"
        "VERIFICACIÓN PROTEÍNA — OBLIGATORIA en almuerzo/cena: "
        "antes de finalizar, confirmá que hay una fuente proteica principal "
        "(carne, pollo, pescado, mariscos, huevo, legumbre). "
        "Si no ves ninguna, REVISÁ — puede estar bajo salsa, semioculta o en el borde. "
        "Un plato de almuerzo/cena sin proteína es inusual; buscala activamente.\n"
        "SOPAS/CREMAS CON SÓLIDOS: si el plato base es sopa/crema pero hay sólidos "
        "VISIBLES (trozos de carne, papa, verdura, legumbre), listalós POR SEPARADO "
        "además de la base líquida. La base es UN ítem; cada sólido es otro ítem.\n"
        "SNACK CON MÚLTIPLES INGREDIENTES: en snacks con 2-4 componentes "
        "(frutas + nueces, queso + crackers, yogur + granola), verificá que TODOS "
        "estén listados. Nueces, frutos secos y frutos rojos son pequeños y fáciles "
        "de omitir aunque estén claramente presentes.\n"
        "CENSO OBLIGATORIO (`unit_census`, va ANTES de `items`): "
        "una línea con las piezas enteras repetidas — ej. 'carne:2; huevo:1; empanada:3'. "
        "Copia ese conteo al `count` de cada ítem pieza_entera.\n"
        "CONTEO DE APILADOS: para piezas enteras repetidas, ubica y cuenta CADA unidad "
        "incluyendo las apiladas u ocultas detrás de otra. "
        "Ante duda 1 vs 2+, mira grosor (doble alto=2), bordes (dos contornos=2) "
        "y sombras entre capas. No asumas 1 por defecto.\n"
        "ALIMENTOS LICUADOS/MEZCLADOS (batido, smoothie, gachas, porridge, crema, puré): "
        "listá los ingredientes densos invisibles probables dentro del blend "
        "(aguacate, plátano, leche entera, mantequilla de maní, miel, semillas) "
        "como ítems separados con confidence apropiado.\n"
        "Por cada alimento: name, confidence (0..1), group, role, prep_method, count, portion_kind.\n"
        "group: vegetable|fruit|grain|protein|dairy|fat|sweet|beverage|other\n"
        "role: main|side|sauce|condiment|cooking_fat|garnish|sweetener|beverage_base\n"
        "prep_method: grilled|fried|deep_fried|boiled|raw|baked|sauteed|steamed|stewed|unknown\n"
        "portion_kind: pieza_entera (piezas contables idénticas) | a_granel (montón/picado/salsa/líquido).\n"
        "count: número de unidades cuando pieza_entera; siempre 1 cuando a_granel.\n"
        "confidence: alto si la identidad es clara; bajo si ocluido, borroso o inferido.\n"
        "IDIOMA: name en el idioma del Locale — 'en' → inglés; cualquier otro → español.\n"
        f"Locale={locale}. Region={region}. JSON estricto, nunca texto libre."
    )


def _estimate_system_prompt(locale: str, region: str) -> str:
    """Stable estimation prompt template for Call 2 of the two-pass pipeline.

    The specific item list is injected as user-message content at call time so
    this template stays stable and its hash is a valid cache-invalidation key.
    Any wording change here changes estimation_prompt_sha256 → cache invalidation.
    """
    return (
        "Eres un experto en nutrición y porciones de hogar LatAm/US/EU.\n"
        "Recibirás una lista de alimentos ya identificados y la imagen original.\n"
        "Tu tarea: para CADA ítem de la lista, estima los gramos VISIBLES EN LA FOTO "
        "y calcula macros con Atwater (kcal = 4·prot + 4·carbs + 9·fat).\n"
        "Responde con un array `estimates` index-alineado a la lista recibida.\n"
        "REGLA MAESTRA: mide lo que REALMENTE hay en el plato — el área que ocupa, "
        "el grosor, la altura del montón. NO asumas una porción 'típica'. "
        "La comida en una foto casera suele ser MÁS PEQUEÑA de lo que parece; "
        "un plato no está lleno hasta el borde.\n"
        "ANCLAS (solo si el tamaño es AMBIGUO u ocluido — nunca como valor por defecto): "
        "proteína (filete/pechuga) 100-150 g; arroz/pasta cocida 100-160 g; "
        "verdura cocida 60-110 g; ensalada/hoja 30-70 g; fruta mediana 100-150 g; "
        "sopa/crema en bol 250-350 g; pan/tostada por rebanada 25-40 g.\n"
        "Si ves el tamaño con claridad, IGNORA las anclas y reporta lo que ves.\n"
        "confidence: alto si tamaño Y tipo son claros; bajo si ocluido o dudoso.\n"
        "Si la lista incluye referencias de porción típica, úsalas como ancla débil, "
        "NO como valor final — la evidencia visual manda.\n"
        "SESGO A CORREGIR: el error #1 de los modelos es SOBREESTIMAR el gramaje. "
        "Ante la duda, estimá hacia la porción PEQUEÑA-MEDIANA, no la grande.\n"
        "COTA DE SANIDAD (límite superior, NO objetivo): un total por comida hogar "
        "raramente supera — desayuno ~550, almuerzo ~750, cena ~650, snack ~220 kcal. "
        "Son TECHOS: si tu suma se acerca a ellos, revisá que no estés inflando porciones. "
        "Estar MUY por debajo del techo es normal y correcto.\n"
        "ALIMENTOS LICUADOS/MEZCLADOS (batido, smoothie, gachas, porridge, crema, puré): "
        "pueden ocultar ingredientes densos (aguacate, plátano, leche entera, mantequilla "
        "de maní, miel, semillas, crema). SOLO si tu estimado visible resulta implausiblemente "
        "bajo (batido con lácteos <70 kcal/100ml; con aguacate/nuez/coco <100 kcal/100ml; "
        "gachas con leche <90 kcal/100g), añadí el ingrediente denso más probable. "
        "No agregues densos por defecto — solo para corregir un piso irreal.\n"
        "SOPAS/CREMAS CON SÓLIDOS: si hay sólidos VISIBLES (trozos de carne, papa, verdura "
        "entera, legumbre), listalós POR SEPARADO además de la base líquida. "
        "La base líquida es UN ítem; cada sólido identificable es otro ítem adicional.\n"
        "SNACK CON MÚLTIPLES INGREDIENTES: en snacks con 2-4 componentes "
        "(frutas + nueces, queso + crackers, yogur + granola), verificá que TODOS estén listados, "
        "pero en las porciones PEQUEÑAS propias de un snack (nueces ~15 g, no ~50 g).\n"
        f"Locale={locale}. Region={region}. JSON estricto."
    )


_IDENTIFY_ROLES: frozenset[str] = frozenset(
    {"main", "side", "sauce", "condiment", "cooking_fat", "garnish", "sweetener", "beverage_base"}
)
_IDENTIFY_PREP_METHODS: frozenset[str] = frozenset(
    {"grilled", "fried", "deep_fried", "boiled", "raw", "baked", "sauteed", "steamed", "stewed", "unknown"}
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


def _normalize_reasoning_effort(model: str, effort: str) -> str:
    """Map the 'no reasoning' effort value to the one the model accepts.

    Valid values DIFFER by family: gpt-5 / gpt-5-mini accept 'minimal' (reject
    'none'); gpt-5.4 / nano accept 'none' (reject 'minimal' → HTTP 400). So a
    stale env var (e.g. VISION_REASONING_EFFORT=minimal after switching to nano)
    would 400 every vision call. Normalise here so config can't break the call.
    """
    m = model.lower()
    is_54 = "5.4" in m or "nano" in m
    if is_54 and effort == "minimal":
        return "none"
    if not is_54 and effort == "none":
        return "minimal"
    return effort


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
                "reasoning_effort": _normalize_reasoning_effort(model, s.vision_reasoning_effort),
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

    # ------------------------------------------------------------------
    # Two-pass protocol implementations
    # ------------------------------------------------------------------

    def identification_prompt_sha256(self, *, locale: str, region: str) -> str:
        """SHA256 of the Call-1 (identification) system prompt template.

        Used by the two-pass cache layer for invalidation when the prompt changes.
        Pure function — no I/O.
        """
        return hashlib.sha256(_identify_system_prompt(locale, region).encode()).hexdigest()

    def estimation_prompt_sha256(self, *, locale: str, region: str) -> str:
        """SHA256 of the Call-2 (estimation) system prompt template.

        Pure function — no I/O.
        """
        return hashlib.sha256(_estimate_system_prompt(locale, region).encode()).hexdigest()

    async def _invoke_with_schema(  # noqa: PLR0913 — cohesive call params
        self,
        *,
        model: str,
        sys_prompt: str,
        user_content: list[dict[str, Any]],
        detail: DetailLevel,
        user_id: UUID | None,
        max_output_tokens: int,
        schema_name: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        """Raw API call with a custom JSON schema. Returns parsed dict.

        Shares cost-cap, circuit-breaker, and retry logic with ``_invoke``.
        Returns the parsed JSON dict so callers can extract their own typed values.
        """
        img_tok = _image_token_estimate(detail)
        in_price = _price_input(model)
        out_price = _price_output(model)
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
                    {"role": "user", "content": user_content},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema_name,
                        "strict": True,
                        "schema": schema,
                    },
                },
                **_completion_kwargs(model, max_output_tokens),
            )
            content = resp.choices[0].message.content or "{}"
            usage = resp.usage
            _cached_tok = 0
            if (
                usage
                and hasattr(usage, "prompt_tokens_details")
                and usage.prompt_tokens_details
            ):
                _cached_tok = (
                    getattr(usage.prompt_tokens_details, "cached_tokens", 0) or 0
                )
            await record_usage(
                user_id=user_id,
                model=model,
                in_tok=(getattr(usage, "prompt_tokens", 0) if usage else img_tok),
                out_tok=(
                    getattr(usage, "completion_tokens", 0)
                    if usage
                    else max_output_tokens
                ),
                cached_tok=_cached_tok,
            )
            try:
                parsed: dict[str, Any] = json.loads(content)
            except json.JSONDecodeError as je:
                VISION_PARSE_ERRORS.labels(model=model).inc()
                log.warning(
                    "vision.invoke_raw.parse_error",
                    model=model,
                    schema=schema_name,
                    err=str(je)[:200],
                    content_len=len(content),
                )
                parsed = {}
            return parsed

        attempt = 0
        last_exc: Exception | None = None
        while attempt <= MAX_RETRIES:
            try:
                return await _breaker.call(_call)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                attempt += 1
                if attempt > MAX_RETRIES:
                    break
                await asyncio.sleep(0.5 * (2 ** (attempt - 1)))

        log.warning(
            "vision.invoke_raw.failed",
            model=model,
            schema=schema_name,
            error=str(last_exc),
        )
        raise UpstreamError(f"vision_raw_failed:{last_exc!s}")

    async def identify(
        self,
        *,
        image_bytes: bytes,
        mime: str,
        user_id: UUID | None,
        locale: str,
        region: str,
        meal_time: str | None = None,
        plan_context: str | None = None,
        user_context: str | None = None,
        model: str | None = None,
    ) -> tuple[list[FoodIdentification], str]:
        """Call 1 — identity only.  MUST NOT return amounts.

        Returns ``(identifications, prompt_sha256)`` where ``prompt_sha256``
        is the SHA of the *stable* system prompt (locale + region only).
        """

        s = get_settings()
        effective_model = model or self._primary_model()

        prompt = _identify_system_prompt(locale, region)
        prompt_sha = hashlib.sha256(prompt.encode()).hexdigest()

        # Inject per-call context into the system prompt (does not affect hash)
        prompt_full = prompt
        if meal_time:
            prompt_full += f"\nComida: {meal_time}."
        if plan_context:
            prompt_full += (
                f"\nContexto del plan: {plan_context}. "
                "Si ves los mismos ingredientes, priorizalos."
            )
        if user_context:
            prompt_full += (
                f"\nContexto de esta foto (usuario): «{user_context}»."
            )

        detail: DetailLevel = await asyncio.to_thread(
            _detect_detail_level, image_bytes, s.vision_low_detail_max_dim
        )
        b64 = base64.b64encode(image_bytes).decode()
        data_url = f"data:{mime};base64,{b64}"

        user_content: list[dict[str, Any]] = [
            {"type": "text", "text": "Identifica los alimentos en esta imagen."},
            {"type": "image_url", "image_url": {"url": data_url, "detail": detail}},
        ]

        raw = await self._invoke_with_schema(
            model=effective_model,
            sys_prompt=prompt_full,
            user_content=user_content,
            detail=detail,
            user_id=user_id,
            max_output_tokens=s.vision_identify_max_output_tokens,
            schema_name="vision_identify",
            schema=IDENTIFY_SCHEMA,
        )

        ids = _parse_identifications(raw)
        log.info(
            "vision.identify.done",
            n_items=len(ids),
            model=effective_model,
            prompt_sha=prompt_sha[:8],
        )
        return ids, prompt_sha

    async def estimate(
        self,
        *,
        image_bytes: bytes,
        mime: str,
        identifications: Sequence[FoodIdentification],
        portion_hints: Mapping[int, PortionHint] | None = None,
        user_id: UUID | None,
        locale: str,
        region: str,
        meal_time: str | None = None,
        user_profile: dict[str, object] | None = None,
        portion_history: list[str] | None = None,
        user_context: str | None = None,
        model: str | None = None,
    ) -> tuple[list[PortionEstimate], str]:
        """Call 2 — grams/macros for a FIXED item list, from the SAME image.

        Returns ``(estimates, prompt_sha256)`` where ``prompt_sha256``
        is the SHA of the *stable* system prompt (locale + region only).
        """

        s = get_settings()
        effective_model = model or self._primary_model()

        prompt = _estimate_system_prompt(locale, region)
        prompt_sha = hashlib.sha256(prompt.encode()).hexdigest()

        # Build system prompt with per-call context (does not affect hash)
        prompt_full = prompt
        if meal_time:
            # Techo de sanidad (NO objetivo) — coherente con la COTA del prompt.
            # Estar por debajo es normal; el framing evita anclar al alza.
            _meal_kcal_ceiling = {
                "breakfast": "~550 kcal",
                "lunch": "~750 kcal",
                "dinner": "~650 kcal",
                "snack": "~220 kcal",
            }
            kcal_ceiling = _meal_kcal_ceiling.get(meal_time, "")
            prompt_full += (
                f"\nComida del día: {meal_time}."
                + (
                    f" Techo de sanidad (no objetivo): {kcal_ceiling}; estar por debajo es normal."
                    if kcal_ceiling
                    else ""
                )
            )
        if user_profile:
            sex = user_profile.get("sex", "")
            age = user_profile.get("age", "")
            weight = user_profile.get("weight_kg", "")
            prompt_full += (
                f"\nPerfil del usuario: {sex}, {age} años, {weight}kg."
            )
        if user_context:
            prompt_full += (
                f"\nContexto de esta foto (usuario): «{user_context}». "
                "Señal más fuerte para calibrar tamaño de porciones."
            )

        # Build user message: items list + optional hints + image
        items_lines = [
            f"{i}: {ident.name} ({ident.group})"
            for i, ident in enumerate(identifications)
        ]
        items_text = "\n".join(items_lines)

        hints_text = ""
        if portion_hints:
            hint_lines: list[str] = []
            for idx, hint in portion_hints.items():
                if hint.typical_serving_g is not None:
                    hint_lines.append(
                        f"  {idx}: {hint.name_norm} → ~{hint.typical_serving_g:.0f}g típico"
                    )
            if hint_lines:
                hints_text = "\nReferencias de porción:\n" + "\n".join(hint_lines)

        if portion_history:
            history_text = ", ".join(portion_history[:3])
            hints_text += (
                f"\nPorciones habituales del usuario: {history_text}. "
                "Calibra si reconoces los mismos alimentos."
            )

        user_text = (
            f"Alimentos identificados:\n{items_text}{hints_text}\n\n"
            "Para CADA ítem (por su índice), estima los gramos visibles y los macros."
        )

        detail: DetailLevel = await asyncio.to_thread(
            _detect_detail_level, image_bytes, s.vision_low_detail_max_dim
        )
        b64 = base64.b64encode(image_bytes).decode()
        data_url = f"data:{mime};base64,{b64}"

        user_content: list[dict[str, Any]] = [
            {"type": "text", "text": user_text},
            {"type": "image_url", "image_url": {"url": data_url, "detail": detail}},
        ]

        raw = await self._invoke_with_schema(
            model=effective_model,
            sys_prompt=prompt_full,
            user_content=user_content,
            detail=detail,
            user_id=user_id,
            max_output_tokens=s.vision_max_output_tokens,
            schema_name="vision_estimate",
            schema=ESTIMATE_SCHEMA,
        )

        raw_estimates = _parse_estimates(raw)
        n_ids = len(identifications)
        estimates: list[PortionEstimate] = []
        for e in raw_estimates:
            if e.index >= n_ids:
                log.warning(
                    "vision.estimate.index_out_of_range",
                    index=e.index,
                    n_items=n_ids,
                )
            else:
                estimates.append(e)
        log.info(
            "vision.estimate.done",
            n_estimates=len(estimates),
            n_items=n_ids,
            model=effective_model,
            prompt_sha=prompt_sha[:8],
        )
        return estimates, prompt_sha

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
        user_context: str | None = None,
        meal_time: str | None = None,
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
            user_context=user_context,
            meal_time=meal_time,
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
            # Pre-domain guard: cap raw LLM grams here; decompose() re-caps after floor/inference.
            return cap_implausible_portions(full_items, slot=meal_time), prompt_sha

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
            # Pre-domain guard: cap raw LLM grams here; decompose() re-caps after floor/inference.
            return cap_implausible_portions(primary_items, slot=meal_time), prompt_sha

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
            # Pre-domain guard: cap raw LLM grams here; decompose() re-caps after floor/inference.
            return cap_implausible_portions(primary_items, slot=meal_time), prompt_sha

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
            # Pre-domain guard: cap raw LLM grams here; decompose() re-caps after floor/inference.
            return cap_implausible_portions(primary_items, slot=meal_time), prompt_sha

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
        # Pre-domain guard: cap raw LLM grams here; decompose() re-caps after floor/inference.
        return cap_implausible_portions(fallback_items, slot=meal_time), prompt_sha

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

# OIL_ABSORPTION_PCT and OIL_KCAL_PER_G live in plate_decomposition (domain) —
# single source of truth (deep_fried=0.12, fried=0.10, sauteed=0.04). Imported above.

# Cap absorbed oil at 10 g per plate (90 kcal). A generous deep-fried portion
# (200g chicken × 0.10 = 20g) is capped here because the LLM already accounts
# for visible oil shine in its kcal estimate; injecting more causes MAE regression.
_OIL_INJECTION_CAP_G = 10.0

# Groups whose fat content is already tracked in their own macros — adding
# cooking-fat on top would double-count.
# "grain" added: rice/pasta/bread macros already include any absorbed fat.
_OIL_SKIP_GROUPS: frozenset[str] = frozenset({"fat", "sweet", "beverage", "fruit", "grain"})


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
    """Inject inferred cooking-fat item for deep-fried and pan-fried foods.

    Skips if LLM already detected a cooking_fat role item — no double-counting.
    Aggregates absorbed oil across all fried items into one inferred entry.
    Absorption uncertainty: -20% / +40% (asymmetric — easier to absorb more).
    """
    if any(i.role == "cooking_fat" for i in items):
        return items

    total_oil_g = 0.0
    for item in items:
        pct = OIL_ABSORPTION_PCT.get(item.prep_method or "")
        if pct is None:
            continue
        # Skip groups whose fat is already part of their macro profile.
        if (item.food_group or "other") in _OIL_SKIP_GROUPS:
            continue
        amount_g = float(item.estimated_amount_g)
        if amount_g <= 0:
            continue
        total_oil_g += amount_g * pct

    if total_oil_g < 1.0:
        return items

    # Hard cap: beyond this the model misclassified a non-fried item.
    total_oil_g = min(total_oil_g, _OIL_INJECTION_CAP_G)
    oil_g = round(total_oil_g)
    oil_kcal = round(total_oil_g * OIL_KCAL_PER_G)
    oil_kcal_min = round(total_oil_g * 0.8 * OIL_KCAL_PER_G)
    oil_kcal_max = round(total_oil_g * 1.4 * OIL_KCAL_PER_G)

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

            # Invalidate physically impossible prep_method/food_group pairs.
            # These indicate model hallucination: fruit/fat/sweet/beverage items
            # cannot absorb cooking oil — assigning them a frying prep_method
            # corrupts both downstream oil injection and food log data.
            # Applies to ANY food in these groups, not just specific items.
            if prep in OIL_ABSORPTION_PCT and (group if group in _FOOD_GROUPS else "other") in _OIL_SKIP_GROUPS:
                log.info(
                    "vision.parse.prep_method_invalidated",
                    name=str(r.get("name", "?"))[:60],
                    food_group=group,
                    prep_method_llm=prep,
                )
                prep = "unknown"

            # count: number of identical visible units (2 patties, 3 pancakes…).
            # LLM returns per-unit amounts; we multiply deterministically here
            # so the rest of the pipeline always works with totals.
            count = max(1, int(r.get("count") or 1))
            # Hard guard: bulk foods (diced meat, fries, onion rings, sauces) are
            # ONE portion by weight, never repeated units. The model classifies
            # via `portion_kind` (generated before count); if it says 'a_granel'
            # we clamp count=1 so a weak model over-counting chunks can't inflate
            # kcal. estimated_amount_g already holds the whole-pile weight.
            if str(r.get("portion_kind") or "").lower() == "a_granel" and count > 1:
                log.info(
                    "vision.parse.bulk_count_clamped",
                    name=str(r.get("name", "?"))[:60],
                    count_llm=count,
                )
                count = 1

            protein_g = max(0, int(r["protein_g"])) * count
            carbs_g = max(0, int(r["carbs_g"])) * count
            fat_g = max(0, int(r["fat_g"])) * count
            kcal_raw = max(0, int(r["kcal"])) * count
            llm_amount_g = float(r["estimated_amount_g"])

            # size_category catalog override — DISABLED 2026-07-25 after 3 live
            # golden-set runs showed it net-negative: pass rate 39.3%→32.1%→25.0%,
            # kcal MAE 120→215. The fixed (food_type, size_bucket) gram table is
            # less accurate than the LLM's own contextual estimate from the actual
            # photo (a rigid bucket can't tell "rice as sushi roll filling" from
            # "rice as dinner side"). PORTION_GRAMS/resolve_grams kept in the
            # codebase for a future recalibration against golden-set ground truth,
            # but not applied here until re-validated live.
            amount_g = llm_amount_g * count

            # Physical macro sanity guard: sum of macros cannot exceed food weight.
            # Dry foods (nuts, grains) have sum ≈ amount_g; wet foods (fruit, veg)
            # have sum << amount_g (water makes up the rest). Exceeding amount_g is
            # physically impossible — it means the LLM hallucinated macro values.
            # When violated, scale all macros down proportionally so the ratios are
            # preserved but the total becomes physically plausible.
            macro_sum = protein_g + carbs_g + fat_g
            if macro_sum > amount_g and macro_sum > 0:
                scale = amount_g / macro_sum
                protein_g = int(protein_g * scale)
                carbs_g = int(carbs_g * scale)
                fat_g = int(fat_g * scale)
                log.info(
                    "vision.parse.macro_overflow_clamped",
                    name=str(r.get("name", "?"))[:60],
                    macro_sum_g=round(macro_sum),
                    amount_g=round(amount_g),
                    scale=round(scale, 3),
                )

            # Parse-time Atwater (15%): fixes LLM arithmetic on raw output. Distinct from
            # macro_grounder.reconcile_kcal_atwater (40%, post-USDA) which only repairs pipeline bugs.
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
    return _hidden_calorie_post_pass(_dedup_items(out))


def _dedup_items(items: list[DetectedFoodItem]) -> list[DetectedFoodItem]:
    """Merge duplicate items the model emitted multiple times for the same food.

    Duplicates share a normalized name + food_group. Macros and grams are
    summed; confidence is averaged; bbox is discarded (no longer meaningful
    for a merged multi-detection). Inferred items are never merged with
    real detections. Logs when a merge happens so ops can track LLM drift.

    This guards against the class of hallucination where the model lists
    "salmón a la horno" four times for a single fillet, inflating kcal 4×.
    The root cause is the LLM re-listing the same food under slight name
    variants — dedup is the correct defensive layer, not prompt tweaking,
    because prompt changes are model-version fragile.
    """
    def _norm_key(it: DetectedFoodItem) -> str:
        n = _re.sub(r"[\s\-_/,.()\[\]]+", " ", it.name.lower()).strip()
        return f"{n}|{it.food_group or 'other'}"

    seen: dict[str, DetectedFoodItem] = {}
    for it in items:
        key = _norm_key(it)
        if key not in seen:
            seen[key] = it
            continue
        existing = seen[key]
        # Keep first occurrence — duplicates are re-listings of the same food,
        # not additional portions. Summing grams inflates 4× for one fillet into
        # 4× kcal. The LLM uses `count` field when there are genuinely multiple
        # pieces; duplicate *names* mean a single item re-listed.
        log.info(
            "vision.parse.dedup_dropped",
            name=it.name[:60],
            food_group=it.food_group,
            kept_g=float(existing.estimated_amount_g),
            dropped_g=float(it.estimated_amount_g),
        )
        seen[key] = _dc_replace(
            existing,
            confidence=round((existing.confidence + it.confidence) / 2, 3),
            bbox=None,
        )
    return list(seen.values())


# ---------------------------------------------------------------------------
# Two-pass parsers
# ---------------------------------------------------------------------------


def _parse_identifications(raw: dict[str, Any]) -> list[FoodIdentification]:
    """Parse Call-1 (identify) JSON into ``FoodIdentification`` objects.

    Malformed rows are logged and skipped — never raise here so a single bad
    item never drops the whole identification.
    """
    out: list[FoodIdentification] = []
    for r in raw.get("items", []) or []:
        try:
            group_raw = str(r.get("group", "other"))
            group: FoodGroup = group_raw if group_raw in _FOOD_GROUPS else "other"  # type: ignore[assignment]

            role_raw = str(r.get("role") or "") or None
            role = role_raw if role_raw in _IDENTIFY_ROLES else None

            prep_raw = str(r.get("prep_method") or "") or None
            prep = prep_raw if prep_raw in _IDENTIFY_PREP_METHODS else None

            count = max(1, int(r.get("count") or 1))
            portion_kind_raw = str(r.get("portion_kind") or "a_granel").lower()
            portion_kind = (
                "pieza_entera"
                if portion_kind_raw == "pieza_entera"
                else "a_granel"
            )
            # Enforce bulk clamp: a_granel items are ONE portion by weight
            if portion_kind == "a_granel" and count > 1:
                count = 1

            confidence = max(0.0, min(1.0, float(r.get("confidence", 0.5))))

            out.append(
                FoodIdentification(
                    name=str(r["name"])[:120],
                    confidence=confidence,
                    group=group,
                    role=role,
                    prep_method=prep,
                    count=count,
                    portion_kind=portion_kind,  # type: ignore[arg-type]
                )
            )
        except (KeyError, ValueError, TypeError) as exc:
            log.info(
                "vision.identify.skip_row",
                error=str(exc),
                name=str(r.get("name", "?"))[:60],
            )
            continue
    return out


def _parse_estimates(raw: dict[str, Any]) -> list[PortionEstimate]:
    """Parse Call-2 (estimate) JSON into ``PortionEstimate`` objects.

    Malformed rows are logged and skipped.
    """
    out: list[PortionEstimate] = []
    for r in raw.get("estimates", []) or []:
        try:
            index = int(r["index"])
            amount_raw = float(r["estimated_amount_g"])
            # Guard against non-positive amounts from the model
            if amount_raw <= 0:
                amount_raw = 1.0
            amount_g = Decimal(str(round(amount_raw, 1)))

            kcal = max(0, int(r["kcal"]))
            protein_g = max(0, int(r["protein_g"]))
            carbs_g = max(0, int(r["carbs_g"]))
            fat_g = max(0, int(r["fat_g"]))
            confidence = max(0.0, min(1.0, float(r.get("confidence", 0.5))))

            out.append(
                PortionEstimate(
                    index=index,
                    estimated_amount_g=amount_g,
                    kcal=kcal,
                    protein_g=protein_g,
                    carbs_g=carbs_g,
                    fat_g=fat_g,
                    confidence=confidence,
                )
            )
        except (KeyError, ValueError, TypeError, InvalidOperation) as exc:
            log.info(
                "vision.estimate.skip_row",
                error=str(exc),
                index=str(r.get("index", "?"))[:10],
            )
            continue
    return out
