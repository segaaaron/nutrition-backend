"""Backfill `recipe_components.food_id` by parsing the free_text_name with
gpt-4o-mini → trigram/embedding match against `foods`.

Idempotent: skips rows where food_id is already set.
Cost cap: hard ceiling $2 total (sums per-call estimates and stops).
Batch flag: --batch N (default 100).

Usage:
    python scripts/resolve_ingredients.py --batch 100
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
from decimal import Decimal
from uuid import UUID

from openai import AsyncOpenAI
from sqlalchemy import text

from app.core.config import get_settings
from app.core.cost_cap import estimate_input_cost
from app.core.db import session_scope
from app.core.logging import configure_logging, get_logger
from app.vision.infrastructure.food_matcher import HybridFoodMatcher

log = get_logger("scripts.resolve_ingredients")
HARD_CAP_USD = 2.0


PARSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "nombre": {"type": "string"},
        "cantidad_g": {"type": "number"},
    },
    "required": ["nombre", "cantidad_g"],
}

QTY_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(g|gr|ml|cc)\b", re.IGNORECASE)


def _try_regex(free_text: str) -> tuple[str, float] | None:
    m = QTY_RE.search(free_text)
    if not m:
        return None
    qty = float(m.group(1).replace(",", "."))
    # Strip the leading qty + unit + optional "de".
    name = QTY_RE.sub("", free_text, count=1).strip()
    name = re.sub(r"^(de\s+|of\s+)", "", name, flags=re.IGNORECASE).strip()
    if not name:
        return None
    return (name, qty)


async def _parse_with_llm(free_text: str, client: AsyncOpenAI, model: str) -> tuple[str, float] | None:
    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": (
            "Extrae {nombre, cantidad_g} de este texto de ingrediente. "
            "Si no hay gramos, usa 100. Texto: " + free_text
        )}],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "ingredient", "strict": True, "schema": PARSE_SCHEMA},
        },
        temperature=0.0,
    )
    try:
        d = json.loads(resp.choices[0].message.content or "{}")
        return (str(d["nombre"])[:120], float(d["cantidad_g"]))
    except Exception:  # noqa: BLE001
        return None


async def main(batch: int) -> None:
    configure_logging("INFO")
    s = get_settings()
    client = AsyncOpenAI(api_key=s.openai_api_key or "sk-test", timeout=15.0)
    model = s.openai_chat_model

    cost_spent = 0.0
    n_processed = 0
    n_matched = 0
    triggered_recipes: set[str] = set()

    async with session_scope() as session:
        matcher = HybridFoodMatcher(session)
        rows = (await session.execute(text("""
            SELECT id::text, recipe_id::text, free_text_name
              FROM recipe_components
             WHERE food_id IS NULL AND free_text_name IS NOT NULL
             ORDER BY position
             LIMIT :n
        """), {"n": batch})).all()

        for r in rows:
            comp_id, recipe_id, free_text = r
            # 1) Cheap regex first.
            parsed = _try_regex(free_text)
            # 2) Else mini LLM.
            if not parsed:
                est = estimate_input_cost(model, free_text) + 0.0002
                if cost_spent + est > HARD_CAP_USD:
                    log.warning("resolve.cost_cap_hit", spent=cost_spent)
                    break
                parsed = await _parse_with_llm(free_text, client, model)
                cost_spent += est

            if not parsed:
                continue
            name, qty_g = parsed
            food_id, _name_norm, method = await matcher.match(
                name=name, amount_g=qty_g, locale="es", user_id=None,
            )
            n_processed += 1
            if food_id is None:
                continue
            await session.execute(text("""
                UPDATE recipe_components
                   SET food_id = :fid, amount_g = :ag
                 WHERE id = :id
            """), {"fid": str(food_id), "ag": qty_g, "id": comp_id})
            triggered_recipes.add(recipe_id)
            n_matched += 1
            log.info("resolve.match", comp=comp_id[:8], method=method, name=name[:40])

    log.info(
        "resolve.done",
        processed=n_processed, matched=n_matched,
        cost_usd=round(cost_spent, 4),
        triggered_recipes=len(triggered_recipes),
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--batch", type=int, default=100)
    args = p.parse_args()
    asyncio.run(main(args.batch))
