"""Trigram + embedding hybrid food matcher.

Resolution order per detected item:
  1. Personal correction cache (vision_user_corrections) — instant.
  2. Trigram match on foods.name_norm (threshold 0.45 similarity, top 5).
  3. Vector cosine on foods.embedding via pgvector HNSW (threshold 0.70).
  Returns the first match above threshold; otherwise (None, None, 'unmatched').

Cost: trigram + embedding query is one round-trip each; the embedder is
shared with the recipes catalog so HNSW index hits the cache.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

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
    def __init__(self, session: AsyncSession, embedder: OpenAIEmbedder | None = None) -> None:
        self.s = session
        self.embedder = embedder or OpenAIEmbedder()

    async def match(
        self,
        *,
        name: str,
        amount_g: float,
        locale: str,
        user_id: UUID | None,
    ) -> tuple[Optional[UUID], Optional[str], str]:
        name_norm = _normalise(name)
        if not name_norm:
            return (None, None, "unmatched")

        # 1) Personal correction.
        if user_id is not None:
            row = (await self.s.execute(
                text("""
                    SELECT corrected_food_id::text
                      FROM vision_user_corrections
                     WHERE user_id = :uid AND detected_name_norm = :n
                       AND corrected_food_id IS NOT NULL
                """),
                {"uid": str(user_id), "n": name_norm},
            )).first()
            if row and row[0]:
                return (UUID(row[0]), name_norm, "personal")

        # 2) Trigram.
        row = (await self.s.execute(
            text("""
                SELECT id::text, name_norm, similarity(name_norm, :n) AS sim
                  FROM foods
                 WHERE name_norm % :n
                 ORDER BY sim DESC
                 LIMIT 1
            """),
            {"n": name_norm},
        )).first()
        if row and row[2] is not None and float(row[2]) >= TRIGRAM_THRESHOLD:
            return (UUID(row[0]), row[1], "trigram")

        # 3) Embedding fallback.
        try:
            emb = await self.embedder.embed(name_norm)
        except Exception as exc:  # noqa: BLE001
            log.debug("vision.match.embed_skip", error=str(exc))
            return (None, None, "unmatched")

        vec_lit = "[" + ",".join(f"{x:.6f}" for x in emb) + "]"
        row = (await self.s.execute(
            text(f"""
                SELECT id::text, name_norm, embedding <=> '{vec_lit}'::vector AS dist
                  FROM foods
                 WHERE embedding IS NOT NULL
                 ORDER BY embedding <=> '{vec_lit}'::vector
                 LIMIT 1
            """),
        )).first()
        if row and row[2] is not None and float(row[2]) <= EMBEDDING_COSINE_DISTANCE_MAX:
            return (UUID(row[0]), row[1], "embedding")

        return (None, name_norm, "unmatched")
