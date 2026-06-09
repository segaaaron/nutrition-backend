"""seed_coach_faq.py — populate ``coach_faq`` for Coach Camino 2 (RAG).

Idempotent. Loads FAQs from ``data/coach/faq_seed.yaml``, computes embeddings
with OpenAI ``text-embedding-3-large`` truncated to 1536 dims (matches the
pgvector column declared in migration 0002 and consumed by
``app/coach/application/chat_message.py::_try_faq``), then UPSERTs rows.

Usage:

    # 1. Dry-run — prints cost estimate, NO API calls, NO DB writes:
    python -m scripts.seed_coach_faq --dry-run

    # 2. Stage to a dev DB:
    python -m scripts.seed_coach_faq --execute

    # 3. Force re-seed (truncates table first):
    python -m scripts.seed_coach_faq --execute --reseed

Cost model (2026-Q2 pricing): text-embedding-3-large is $0.13 / 1M tokens.
40-row seed × ~20 tokens/question ≈ 800 tokens ≈ $0.0001. The full file is
priced at < $0.001 — effectively free.

CLAUDE.md compliance:
  - Does NOT touch git.
  - Does NOT auto-run against prod (--execute is opt-in, and even then it
    targets the DATABASE_URL of the *invoking shell*).
  - Idempotency: dedupe on (question_en) — rows are UPSERTed by canonical
    question. With ``--reseed``, the table is TRUNCATED first.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import text

from app.core.db import session_scope
from app.core.logging import configure_logging, get_logger
from app.recipes.infrastructure.openai_embedder import OpenAIEmbedder

log = get_logger("scripts.seed_coach_faq")

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "coach" / "faq_seed.yaml"

# OpenAI text-embedding-3-large @ 2026-Q2 — $0.13 per 1M input tokens.
PRICE_PER_M_TOKENS = Decimal("0.13")
APPROX_TOKENS_PER_QUESTION = 20


def _load(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        log.error("seed.faq.file_not_found", path=str(path))
        sys.exit(2)
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, list) or not data:
        log.error("seed.faq.empty_or_invalid_yaml", path=str(path))
        sys.exit(2)
    for i, row in enumerate(data):
        if not isinstance(row, dict):
            raise SystemExit(f"row {i} is not a dict")
        for k in ("question_en", "answers"):
            if k not in row:
                raise SystemExit(f"row {i} missing required key '{k}'")
        ans = row["answers"]
        if not isinstance(ans, dict) or "en" not in ans:
            raise SystemExit(f"row {i} answers must contain at least 'en'")
    return data


def _format_cost(n_rows: int) -> str:
    tokens = Decimal(n_rows * APPROX_TOKENS_PER_QUESTION)
    usd = (tokens / Decimal("1000000")) * PRICE_PER_M_TOKENS
    return f"{n_rows} rows × ~{APPROX_TOKENS_PER_QUESTION} tokens ≈ {tokens} tokens ≈ ${usd:.6f}"


async def _embed_one(embedder: OpenAIEmbedder, question: str) -> list[float]:
    return await embedder.embed(question)


def _to_pgvector_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


async def _seed(rows: list[dict[str, Any]], *, reseed: bool) -> int:
    embedder = OpenAIEmbedder()
    n_written = 0
    async with session_scope() as session:
        if reseed:
            await session.execute(text("TRUNCATE TABLE coach_faq"))
            log.info("seed.faq.truncated")

        for i, row in enumerate(rows):
            question_en: str = row["question_en"].strip()
            intent = row.get("intent")
            answers: dict[str, str] = {k: v.strip() for k, v in row["answers"].items()}

            try:
                vec = await _embed_one(embedder, question_en)
            except Exception as exc:  # noqa: BLE001
                log.error(
                    "seed.faq.embed_failed",
                    i=i,
                    question=question_en[:80],
                    err=str(exc),
                )
                raise

            vec_lit = _to_pgvector_literal(vec)
            # UPSERT by (question_en). No unique index on the column today;
            # we DELETE-then-INSERT under the assumption that --reseed handles
            # bulk and incremental runs handle small deltas. For incremental
            # use, the script first prunes any existing row with the same
            # question_en, then inserts.
            await session.execute(
                text("DELETE FROM coach_faq WHERE question_en = :q"),
                {"q": question_en},
            )
            # S608 noqa: vec_lit is built from floats formatted via f"{x:.6f}"
            # (no user input). pgvector requires '[...]'::vector literal form;
            # parameter binding is not supported for this operator path.
            await session.execute(
                text(  # noqa: S608
                    f"""
                INSERT INTO coach_faq (
                    id, question_en, answer_translations, intent,
                    embedding, created_at
                ) VALUES (
                    gen_random_uuid(), :q, CAST(:a AS jsonb), :i,
                    '{vec_lit}'::vector, now()
                )
                """
                ),
                {
                    "q": question_en,
                    "a": _jsonify(answers),
                    "i": intent,
                },
            )
            n_written += 1
            log.info("seed.faq.inserted", i=i, question=question_en[:60])

    return n_written


def _jsonify(obj: dict[str, str]) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


async def _main() -> int:
    parser = argparse.ArgumentParser(description="Seed coach_faq with curated FAQs.")
    parser.add_argument(
        "--path",
        type=Path,
        default=DEFAULT_PATH,
        help=f"Path to YAML seed file (default: {DEFAULT_PATH}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate YAML + print cost estimate; do NOT call OpenAI or write DB.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually call OpenAI + write rows. Without this flag the script is a no-op.",
    )
    parser.add_argument(
        "--reseed",
        action="store_true",
        help="TRUNCATE coach_faq first. Use to rebuild from scratch.",
    )
    args = parser.parse_args()

    configure_logging("info")

    rows = _load(args.path)
    log.info(
        "seed.faq.loaded",
        path=str(args.path),
        n_rows=len(rows),
        cost_estimate=_format_cost(len(rows)),
    )

    if args.dry_run or not args.execute:
        log.info("seed.faq.dry_run_no_writes")
        return 0

    n = await _seed(rows, reseed=args.reseed)
    log.info("seed.faq.done", n_written=n)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
