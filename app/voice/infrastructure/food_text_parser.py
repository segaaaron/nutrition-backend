"""NLP food parser — text → list of (food_name, quantity_g).

Two-layer strategy:
  1. Regex + word2number for trivial patterns ("100g de avena", "2 platanos",
     "una manzana grande"). Zero LLM cost.
  2. Fallback to gpt-4o-mini for ambiguous input ("bowl de avena con frutos
     rojos"). Strict JSON schema. Cost cap pre-check.

Heuristic unit assumption: when no grams given for fruits/single items,
use a default portion from a small lookup table (banana=120g, manzana=180g,
plátano=120g, huevo=50g, café=200g, leche=240g).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from openai import AsyncOpenAI

from app.core.circuit_breaker import CircuitBreaker
from app.core.config import get_settings
from app.core.cost_cap import estimate_input_cost, pre_check, record_usage
from app.core.logging import get_logger

log = get_logger("voice.parser")

_breaker = CircuitBreaker(name="openai_food_parser", fail_threshold=3, recovery_timeout_s=30)
_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=get_settings().openai_api_key or "sk-test", timeout=15.0)
    return _client


NUMBER_WORDS_ES = {
    "un": 1,
    "una": 1,
    "uno": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
    "medio": 0.5,
    "media": 0.5,
}
NUMBER_WORDS_EN = {
    "a": 1,
    "an": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "half": 0.5,
}

DEFAULT_PORTION_G = {
    "banana": 120,
    "plátano": 120,
    "platano": 120,
    "manzana": 180,
    "apple": 180,
    "huevo": 50,
    "egg": 50,
    "eggs": 50,
    "café": 200,
    "cafe": 200,
    "coffee": 200,
    "leche": 240,
    "milk": 240,
    "pan": 30,
    "bread": 30,
    "yogurt": 170,
    "yogur": 170,
}

# Pattern: optional number (digit or word) + optional unit (g, gr, ml) + food name.
RE_QTY = re.compile(
    r"(?:(\d+(?:[.,]\d+)?)|("
    + "|".join(list(NUMBER_WORDS_ES) + list(NUMBER_WORDS_EN))
    + r"))\s*(g|gr|gramos|grams|ml|cc)?\s+(?:de\s+|of\s+)?([a-záéíóúñ ]+?)(?:\s+(?:con|and|y|,)|$)",
    re.IGNORECASE,
)


@dataclass(slots=True)
class ParsedItem:
    name: str
    quantity_g: float


def _word_to_num(w: str) -> float | None:
    w = w.lower()
    return NUMBER_WORDS_ES.get(w) or NUMBER_WORDS_EN.get(w)


def parse_regex(text: str) -> list[ParsedItem]:
    """Best-effort deterministic parse. Returns [] if nothing matches."""
    out: list[ParsedItem] = []
    # Split on common connectors first so the regex matches each clause.
    clauses = re.split(r"\s*(?:,| y | con | and | with )\s*", text.strip(), flags=re.IGNORECASE)
    for clause in clauses:
        m = RE_QTY.search(clause + " ")
        if not m:
            # Try bare food name with default portion.
            name = clause.strip().lower()
            for key, default in DEFAULT_PORTION_G.items():
                if key in name:
                    out.append(ParsedItem(name=key, quantity_g=float(default)))
                    break
            continue
        qty_digit, qty_word, unit, name = m.groups()
        qty_n: float
        if qty_digit:
            qty_n = float(qty_digit.replace(",", "."))
        else:
            qty_n = _word_to_num(qty_word) or 1.0
        name_clean = name.strip().lower()
        unit_l = (unit or "").lower()
        if unit_l in ("g", "gr", "gramos", "grams", "ml", "cc"):
            grams = qty_n
        else:
            # Multiplier × default portion.
            grams = qty_n * DEFAULT_PORTION_G.get(name_clean.split()[0], 100.0)
        out.append(ParsedItem(name=name_clean, quantity_g=grams))
    return out


PARSE_SCHEMA: dict[str, Any] = {
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
                    "quantity_g": {"type": "number"},
                },
                "required": ["name", "quantity_g"],
            },
        },
    },
    "required": ["items"],
}


async def parse_llm(text: str, *, user_id: UUID | None) -> list[ParsedItem]:
    model = get_settings().openai_chat_model
    prompt = (
        "Parsea el siguiente texto a una lista JSON {name, quantity_g}. "
        "Asume porciones razonables si no se indica gramaje. Texto: " + text
    )
    est = estimate_input_cost(model, prompt) + 0.0005
    await pre_check(user_id=user_id, estimate_usd=est)

    async def _call() -> list[ParsedItem]:
        resp = await _get_client().chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "food_parse", "strict": True, "schema": PARSE_SCHEMA},
            },
            temperature=0.0,
        )
        content = resp.choices[0].message.content or "{}"
        usage = resp.usage
        await record_usage(
            user_id=user_id,
            model=model,
            in_tok=(getattr(usage, "prompt_tokens", 0) if usage else 0),
            out_tok=(getattr(usage, "completion_tokens", 0) if usage else 0),
        )
        d = json.loads(content)
        return [
            ParsedItem(name=str(i["name"])[:80], quantity_g=float(i["quantity_g"]))
            for i in (d.get("items") or [])
        ]

    try:
        return await _breaker.call(_call)
    except Exception as exc:  # noqa: BLE001
        log.warning("voice.parse_llm.failed", err=str(exc))
        return []


async def parse_food_text(text: str, *, user_id: UUID | None) -> list[ParsedItem]:
    """Hybrid: regex first, fall back to mini if zero items."""
    items = parse_regex(text)
    if items:
        return items
    return await parse_llm(text, user_id=user_id)
