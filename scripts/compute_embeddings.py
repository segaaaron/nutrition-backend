"""Backfill embeddings for `foods` and `recipes` rows where embedding IS NULL.

- Batch 100 per OpenAI call (text-embedding-3-large, dim=1536).
- Resumable: filters `WHERE embedding IS NULL`.
- Cost cap: hard-stops if estimated USD > MAX_USD (default 5.00).
- tqdm progress bar.
- Idempotent.

Pricing reference (2026-05 — text-embedding-3-large): $0.13 per 1M tokens.
Rough token estimate: 0.75 token / character (English+Spanish blended).

Run:
    OPENAI_API_KEY=sk-... uv run python -m scripts.compute_embeddings [--max-usd 5.0]
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import Any

from sqlalchemy import text

from app.core.db import session_scope
from app.core.logging import configure_logging, get_logger

log = get_logger("scripts.compute_embeddings")

BATCH_SIZE = 100
USD_PER_1M_TOKENS = 0.13
TOKENS_PER_CHAR = 0.75


def _estimate_cost_usd(texts: list[str]) -> float:
    chars = sum(len(t) for t in texts)
    tokens = chars * TOKENS_PER_CHAR
    return tokens / 1_000_000 * USD_PER_1M_TOKENS


async def _embed(texts: list[str]) -> list[list[float]]:
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
    resp = await client.embeddings.create(
        model="text-embedding-3-large", input=texts, dimensions=1536,
    )
    return [item.embedding for item in resp.data]


async def _backfill_table(
    table: str,
    text_expr: str,
    max_usd: float,
    spent_usd: float,
) -> tuple[int, float]:
    """Returns (n_updated, new_spent_usd)."""
    updated = 0
    try:
        from tqdm import tqdm  # type: ignore[import-not-found]
    except ImportError:
        def tqdm(it: Any, **_: Any) -> Any:  # type: ignore[misc]
            return it

    async with session_scope() as s:
        # Count remaining
        count_res = await s.execute(text(f"SELECT count(*) FROM {table} WHERE embedding IS NULL"))
        remaining = count_res.scalar_one()
        log.info("compute_embeddings.start", table=table, remaining=remaining)

        pbar = tqdm(total=remaining, desc=f"{table} embeddings")
        while True:
            rows = (await s.execute(text(f"""
                SELECT id, {text_expr} AS doc
                FROM {table}
                WHERE embedding IS NULL
                ORDER BY created_at
                LIMIT :n
            """), {"n": BATCH_SIZE})).all()
            if not rows:
                break

            ids = [r[0] for r in rows]
            docs = [r[1] or "" for r in rows]
            est = _estimate_cost_usd(docs)
            if spent_usd + est > max_usd:
                log.warning(
                    "compute_embeddings.cost_cap_stop",
                    table=table, spent_usd=spent_usd, would_add=est, max_usd=max_usd,
                )
                pbar.close()
                return updated, spent_usd
            try:
                vectors = await _embed(docs)
            except Exception as e:  # noqa: BLE001
                log.error("compute_embeddings.openai_error", table=table, error=str(e))
                pbar.close()
                return updated, spent_usd

            for rid, vec in zip(ids, vectors, strict=True):
                await s.execute(
                    text(f"UPDATE {table} SET embedding = :v WHERE id = :id"),
                    {"v": vec, "id": rid},
                )
            updated += len(rows)
            spent_usd += est
            pbar.update(len(rows))
        pbar.close()
    return updated, spent_usd


async def main() -> int:
    configure_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-usd", type=float, default=5.00)
    parser.add_argument("--only", choices=["foods", "recipes"], default=None)
    args = parser.parse_args()

    if not os.environ.get("OPENAI_API_KEY"):
        log.error("compute_embeddings.no_api_key")
        return 2

    spent = 0.0
    grand_updated = 0

    if args.only in (None, "foods"):
        n, spent = await _backfill_table(
            table="foods",
            text_expr="name_en || ' ' || coalesce(name_translations->>'es', '')",
            max_usd=args.max_usd,
            spent_usd=spent,
        )
        grand_updated += n
    if args.only in (None, "recipes"):
        n, spent = await _backfill_table(
            table="recipes",
            text_expr="name_en || ' ' || coalesce(description_en, '')",
            max_usd=args.max_usd,
            spent_usd=spent,
        )
        grand_updated += n

    log.info("compute_embeddings.complete", updated=grand_updated, spent_usd=round(spent, 4))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
