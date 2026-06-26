"""Layer 3 — Hybrid ranking (taste-EMA + cultural + prep + novelty + adherence).

Composite score per candidate:

    0.40 * cosine(taste_profile, recipe.embedding)
  + 0.20 * cultural_fit(user.country, recipe.regions)
  + 0.20 * prep_time_fit(user.prep_pref_min, recipe.prep_min)
  + 0.10 * novelty(times_seen_last_30d)
  + 0.10 * adherence(completion_rate_for_similar)

The 0.40 vector weight is the largest because pgvector cosine is the most
discriminative signal (1536-dim semantic match). The 0.20+0.20 contextual
band keeps recommendations regionally and operationally relevant. The
0.10+0.10 long-tail band ensures we don't recommend the same dish forever
and that the model preferentially picks recipes the user actually completes.

Budget: <400 ms for K=20 candidates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.plan.application.taste_profile import (
    adherence,
    cosine,
    cultural_fit,
    novelty,
    prep_time_fit,
)


class _ProfileCtx(Protocol):
    async def get_ranking_context(self, user_id: UUID) -> dict: ...


@dataclass(slots=True)
class Layer3Ranking:
    session: AsyncSession
    profile_ctx: _ProfileCtx
    taste_vector: list[float]

    async def __call__(
        self,
        *,
        user_id: UUID,
        candidate_ids: list[UUID],
        meal_time: str,
        novelty_counts: dict[UUID, int] | None = None,
        adherence_rates: dict[UUID, float] | None = None,
        ranking_context: dict | None = None,
        embedding_cache: dict[UUID, tuple[list[str], int | None, list[float]]] | None = None,
    ) -> list[tuple[UUID, float]]:
        if not candidate_ids:
            return []
        # Use pre-fetched context if provided (avoids per-slot DB roundtrip).
        if ranking_context is None:
            ranking_context = await self.profile_ctx.get_ranking_context(user_id)
        country = (ranking_context.get("country") or "").lower() or None
        prep_pref = ranking_context.get("prep_time_pref_min")

        _SQL = text(
            """
            SELECT id, regions, prep_min, embedding
              FROM recipes
             WHERE id = ANY(CAST(:ids AS uuid[]))
        """
        )
        if embedding_cache is not None:
            # Fetch only the subset not yet cached.
            uncached = [cid for cid in candidate_ids if cid not in embedding_cache]
            if uncached:
                res = await self.session.execute(_SQL, {"ids": [str(i) for i in uncached]})
                for row in res.mappings():
                    rid: UUID = row["id"]
                    embedding_cache[rid] = (
                        list(row["regions"] or []),
                        row["prep_min"],
                        list(row["embedding"]) if row["embedding"] is not None else [],
                    )
            rows = [
                {"id": cid,
                 "regions": embedding_cache[cid][0],
                 "prep_min": embedding_cache[cid][1],
                 "embedding": embedding_cache[cid][2]}
                for cid in candidate_ids
                if cid in embedding_cache
            ]
        else:
            res = await self.session.execute(_SQL, {"ids": [str(i) for i in candidate_ids]})
            rows = list(res.mappings())

        novelty_counts = novelty_counts or {}
        adherence_rates = adherence_rates or {}
        # When the taste vector is empty (cold-start user OR catalogue embeddings
        # not backfilled — see DOKPLOY_DEPLOY.md §5), the 0.40 taste weight is
        # redistributed proportionally onto cultural_fit + prep_time_fit so the
        # composite score keeps the same 1.0 envelope and ranking stays
        # meaningful instead of collapsing to a 60%-signal random-ish order.
        taste_active = bool(self.taste_vector)
        w_taste, w_cult, w_prep = (
            (0.40, 0.20, 0.20) if taste_active else (0.0, 0.40, 0.40)
        )
        scored: list[tuple[UUID, float]] = []
        for r in rows:
            rid: UUID = r["id"]
            emb = r["embedding"]
            emb_list = list(emb) if emb is not None else []
            s_taste = cosine(self.taste_vector, emb_list) if taste_active else 0.0
            s_cult = cultural_fit(country, list(r["regions"] or []))
            s_prep = prep_time_fit(prep_pref, r["prep_min"])
            s_nov = novelty(novelty_counts.get(rid, 0))
            s_adh = adherence(adherence_rates.get(rid))
            total = (
                w_taste * s_taste
                + w_cult * s_cult
                + w_prep * s_prep
                + 0.10 * s_nov
                + 0.10 * s_adh
            )
            scored.append((rid, total))
        # Stable tie-break by id: equal scores must rank identically
        # across runs for seeded reproducibility.
        scored.sort(key=lambda x: (-x[1], str(x[0])))
        return scored
