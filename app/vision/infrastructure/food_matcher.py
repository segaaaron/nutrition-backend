"""Trigram + embedding hybrid food matcher.

Resolution order per detected item:
  1. Personal correction cache (vision_user_corrections) — instant.
     Also returns corrected_amount_g if the user previously corrected the portion.
  2. Trigram match on foods.name_norm (threshold 0.45 similarity, top 5).
  3. Vector cosine on foods.embedding via pgvector HNSW (threshold 0.70).
  Returns (food_id, name_norm, method, corrected_amount_g).
  corrected_amount_g is non-None only on personal-correction hits.

Cost: trigram + embedding query is one round-trip each; the embedder is
shared with the recipes catalog so HNSW index hits the cache.

Concurrency note: when `session_factory` is provided (production path),
each `match()` call opens and closes its own `AsyncSession` so N calls can
run concurrently via `asyncio.gather` without violating SQLAlchemy's
single-session-per-task constraint.  When only `session` is given (tests,
legacy callers), the single shared session is used and callers must
serialise their calls.
"""

from __future__ import annotations

import re
import unicodedata
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.logging import get_logger
from app.recipes.infrastructure.openai_embedder import OpenAIEmbedder

log = get_logger("vision.match")

TRIGRAM_THRESHOLD = 0.45
EMBEDDING_COSINE_DISTANCE_MAX = 0.30  # cos_dist <= 0.30 ≈ similarity >= 0.70


def _normalise(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


class HybridFoodMatcher:
    def __init__(
        self,
        session: AsyncSession | None = None,
        embedder: OpenAIEmbedder | None = None,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._session = session
        self._session_factory = session_factory
        self.embedder = embedder or OpenAIEmbedder()

    async def match(
        self,
        *,
        name: str,
        amount_g: float,
        locale: str,
        user_id: UUID | None,
    ) -> tuple[UUID | None, str | None, str, float | None]:
        if self._session_factory is not None:
            async with self._session_factory() as session:
                return await self._do_match(session, name=name, user_id=user_id)
        assert self._session is not None, "HybridFoodMatcher: provide session or session_factory"
        return await self._do_match(self._session, name=name, user_id=user_id)

    async def _do_match(
        self,
        session: AsyncSession,
        *,
        name: str,
        user_id: UUID | None,
    ) -> tuple[UUID | None, str | None, str, float | None]:
        name_norm = _normalise(name)
        if not name_norm:
            return (None, None, "unmatched", None)

        # 1) Personal correction — also returns corrected_amount_g so the
        #    pipeline can apply the user's portion memory (F1.1 fix).
        if user_id is not None:
            row = (
                await session.execute(
                    text(
                        """
                    SELECT corrected_food_id::text, corrected_amount_g
                      FROM vision_user_corrections
                     WHERE user_id = :uid AND detected_name_norm = :n
                       AND corrected_food_id IS NOT NULL
                """
                    ),
                    {"uid": str(user_id), "n": name_norm},
                )
            ).first()
            if row and row[0]:
                corrected_g = float(row[1]) if row[1] is not None else None
                return (UUID(row[0]), name_norm, "personal", corrected_g)

        # 2) Trigram.
        row = (
            await session.execute(
                text(
                    """
                SELECT id::text, name_norm, similarity(name_norm, :n) AS sim
                  FROM foods
                 WHERE name_norm % :n
                 ORDER BY sim DESC
                 LIMIT 1
            """
                ),
                {"n": name_norm},
            )
        ).first()
        if row and row[2] is not None and float(row[2]) >= TRIGRAM_THRESHOLD:
            return (UUID(row[0]), row[1], "trigram", None)

        # 3) Embedding fallback.
        try:
            emb = await self.embedder.embed(name_norm)
        except Exception as exc:  # noqa: BLE001
            log.debug("vision.match.embed_skip", error=str(exc))
            return (None, None, "unmatched", None)

        # S608 noqa: vec_lit is constructed exclusively from floats formatted via
        # f"{x:.6f}" (no user input reaches the SQL string). pgvector requires the
        # literal vector form '[..]'::vector; parameter binding is not supported
        # for this operator path. Safe — not an injection risk.
        vec_lit = "[" + ",".join(f"{x:.6f}" for x in emb) + "]"
        row = (
            await session.execute(
                text(
                    f"""
                SELECT id::text, name_norm, embedding <=> '{vec_lit}'::vector AS dist
                  FROM foods
                 WHERE embedding IS NOT NULL
                 ORDER BY embedding <=> '{vec_lit}'::vector
                 LIMIT 1
            """  # noqa: S608 — vec_lit is float-only literal; pgvector requires inline form
                ),
            )
        ).first()
        if row and row[2] is not None and float(row[2]) <= EMBEDDING_COSINE_DISTANCE_MAX:
            return (UUID(row[0]), row[1], "embedding", None)

        return (None, name_norm, "unmatched", None)
