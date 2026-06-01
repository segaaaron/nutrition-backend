"""Intent classifier — keyword first (zero LLM), gpt-4o-mini fallback.

Returns one of `Intent`. Medical-risk patterns short-circuit to
MEDICAL_REDIRECT regardless of LLM result (Camino 4).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from openai import AsyncOpenAI

from app.coach.domain.value_objects import Intent
from app.core.circuit_breaker import CircuitBreaker
from app.core.config import get_settings
from app.core.cost_cap import estimate_input_cost, pre_check, record_usage
from app.core.logging import get_logger

log = get_logger("coach.intent")

_breaker = CircuitBreaker(name="openai_intent", fail_threshold=3, recovery_timeout_s=30)
_client: AsyncOpenAI | None = None


# Medical-risk hard list (Spanish + English). Triggers Camino 4 zero-cost refuse.
MEDICAL_PATTERNS = [
    r"\b(s[íi]ntoma|symptom|mareo|n[áa]usea|dolor|pain|fever|fiebre|sangra|bleed)\b",
    r"\b(metformin|insulin|warfarin|ssri|antidepres|medicament|medication|pastilla)\b",
    r"\b(embaraz|pregnan|lactanc|breastfeed)\b",
    r"\b(diagnos|cancer|tumor|infarct|stroke|ictus|arritmia|arrhythm)\b",
    r"\b(presion alta|high blood pressure|hipoglucem|hypoglyc)\b",
    # GLP-1 / weight-loss drugs (LatAm + US common).
    r"\b(ozempic|wegovy|mounjaro|saxenda)\b",
    r"\b(liraglutid|semaglutid|tirzepatid)[ae]?\b",
    r"\b(glp[\-\s]?1|agonista glp)\b",
    # Thyroid + endocrine meds.
    r"\b(tiroides|levotiroxin|synthroid|eutirox)\b",
    r"\b(hipo|hiper)tiroid(ismo|eo)?\b",
    # Mental-health symptoms (not nutrition scope).
    r"\b(ansiedad|anxiety|depresi[óo]n|depression|insomnio|insomnia|p[áa]nico|panic|trastorno)\b",
    # Supplement clinical dosing (high-risk advice).
    r"\b(creatina|creatine|bcaa|preworkout|pre[\s\-]?workout|protein.{0,5}powder)\b.{0,30}\b(dosis|dose|cu[áa]nto|how much)\b",
    # Extended fasting (>48h) — clinical territory.
    r"\b(ayuno.{0,20}prolongado|fasting.{0,10}days|cetosis|ketosis|keto.{0,10}flu)\b",
]
_MED_RE = re.compile("|".join(MEDICAL_PATTERNS), re.IGNORECASE)


# Off-topic hard list — query unrelated to nutrition. Zero-cost refuse.
OFFTOPIC_PATTERNS = [
    r"\b(pol[íi]tica|politics|trump|biden|maduro|petro|milei|boric|lula|amlo|sheinbaum)\b",
    r"\b(bitcoin|btc|crypto|nft|inversi[óo]n|stock|bolsa|trading)\b",
    r"\b(programa(r|ci[óo]n)?|c[oó]digo|python|javascript|sql|html|css|java\b)\b",
    r"\b(chiste|joke|adivinanza|broma|riddle)\b",
    r"\b(f[uú]tbol|soccer|basket|tennis|messi|ronaldo|nba)\b",
    r"\b(pel[íi]cula|movie|netflix|spotify|tiktok\b|instagram\b)\b",
    r"\b(novia|girlfriend|boyfriend|relaci[óo]n|breakup)\b",
    r"\b(clima|weather|tiempo.{0,15}(hoy|today|ma[ñn]ana))\b",
]
_OFFTOPIC_RE = re.compile("|".join(OFFTOPIC_PATTERNS), re.IGNORECASE)


# Prompt-injection patterns. Match → refuse + log security event.
INJECTION_PATTERNS = [
    r"\bignore\s+(previous|above|prior|all)\s+(instructions?|prompts?|rules?)\b",
    r"\b(olvida|ignora)\s+(las\s+)?(instrucciones|reglas|prompts?)\b",
    r"\bact\s+as\s+(?!a\s+nutritionist|un\s+nutricionista)",
    r"\b(act[úu]a|comp[óo]rtate|s[ée])\s+como\s+(?!un\s+nutricionista|a\s+nutritionist)",
    r"\b(system\s+prompt|prompt\s+del\s+sistema|tu\s+prompt)\b",
    r"</?\s*system\s*>",
    r"```\s*(system|instructions?)",
    r"\b(jailbreak|dan\s+mode|developer\s+mode)\b",
    r"\b(reveal|muestra|dime|enseña)\s+(tu|tus|your)\s+(prompt|instrucciones|reglas)\b",
]
_INJECTION_RE = re.compile("|".join(INJECTION_PATTERNS), re.IGNORECASE)


# Template intent regex — keyword router.
TEMPLATE_PATTERNS: list[tuple[Intent, re.Pattern]] = [
    (Intent.VIEW_TODAY_PLAN, re.compile(r"\b(plan( de)? (hoy|today)|what'?s my plan)\b", re.I)),
    (Intent.NEXT_MEAL, re.compile(r"\b(pr[óo]xima comida|next meal|que como ahora)\b", re.I)),
    (Intent.STREAK_STATUS, re.compile(r"\b(racha|streak)\b", re.I)),
    (Intent.WATER_PROGRESS, re.compile(r"\b(agua|water)\b.*\b(hoy|today|progress|llevo)\b", re.I)),
    (Intent.PROTEIN_REMAINING, re.compile(r"\b(prote[íi]na|protein).*(falta|remain|left)\b", re.I)),
    (Intent.MARK_WATER, re.compile(r"\b(toma|tom[eé]|bebe|drank|marca|register).{0,15}(agua|water)\b", re.I)),
    (Intent.SWAP_MEAL, re.compile(r"\b(cambia|swap|reemplaz|replace)\b", re.I)),
    (Intent.WHY_PLAN, re.compile(r"\b(por qu[eé]|why).{0,30}(plan|comida|meal)\b", re.I)),
    (Intent.IM_HUNGRY, re.compile(r"\b(hambre|hungry|snack)\b", re.I)),
    (Intent.ALLERGY_UPDATE, re.compile(r"\b(alerg|allerg|intoleran)\b", re.I)),
    (Intent.PLATEAU, re.compile(r"\b(estanca|plateau|no bajo|don'?t lose)\b", re.I)),
]


SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "intent": {"type": "string", "enum": [i.value for i in Intent]},
        "confidence": {"type": "number"},
    },
    "required": ["intent", "confidence"],
}


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=get_settings().openai_api_key or "sk-test", timeout=10.0)
    return _client


@dataclass(slots=True)
class HybridIntentClassifier:
    async def classify(
        self, *, text: str, locale: str, user_id: UUID | None,
    ) -> tuple[Intent, float]:
        # Hard prompt-injection guard — never reach LLM. Logged as security.
        if _INJECTION_RE.search(text):
            log.warning("coach.injection_attempt", user_id=str(user_id), text=text[:200])
            return (Intent.PROMPT_INJECTION, 1.0)
        # Hard medical refuse — never reach LLM.
        if _MED_RE.search(text):
            return (Intent.MEDICAL_REDIRECT, 1.0)
        # Hard off-topic refuse — never reach LLM.
        if _OFFTOPIC_RE.search(text):
            return (Intent.OFFTOPIC_REDIRECT, 1.0)
        # Cheap template router.
        for intent, pat in TEMPLATE_PATTERNS:
            if pat.search(text):
                return (intent, 0.95)
        # LLM fallback for general / ambiguous.
        return await self._llm(text, user_id)

    async def _llm(self, text: str, user_id: UUID | None) -> tuple[Intent, float]:
        model = get_settings().openai_chat_model
        prompt = (
            "Clasifica la siguiente consulta de usuario de una app de nutrición "
            "en exactamente uno de los intents disponibles. Si no calza claramente, "
            "usa 'general'. Texto: " + text[:500]
        )
        est = estimate_input_cost(model, prompt) + 0.0001
        try:
            await pre_check(user_id=user_id, estimate_usd=est)
        except Exception:  # noqa: BLE001 — cost cap → default general
            return (Intent.GENERAL, 0.4)

        async def _call() -> tuple[Intent, float]:
            resp = await _get_client().chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "intent", "strict": True, "schema": SCHEMA},
                },
                temperature=0.0,
            )
            content = resp.choices[0].message.content or "{}"
            usage = resp.usage
            await record_usage(
                user_id=user_id, model=model,
                in_tok=(getattr(usage, "prompt_tokens", 0) if usage else 0),
                out_tok=(getattr(usage, "completion_tokens", 0) if usage else 0),
            )
            d = json.loads(content)
            try:
                return (Intent(d["intent"]), float(d["confidence"]))
            except Exception:  # noqa: BLE001
                return (Intent.GENERAL, 0.3)

        try:
            return await _breaker.call(_call)
        except Exception as exc:  # noqa: BLE001
            log.warning("coach.intent.llm_failed", err=str(exc))
            return (Intent.GENERAL, 0.2)
