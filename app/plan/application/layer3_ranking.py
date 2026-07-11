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
    gl_penalty,
    novelty,
    omega3_fit,
    prep_time_fit,
)

# Conditions for which oily fish / omega-3 is first-line diet therapy get a
# ranking bonus that lifts high-omega-3 recipes (so plans actually include the
# 2-3 fish meals/week the NAFLD literature calls for), on top of the Layer 1
# saturated-fat/sugar safety gate. Additive and condition-scoped: users without
# these conditions rank exactly as before.
_OMEGA3_PROMOTE_CONDITIONS = frozenset({"fatty_liver"})
_OMEGA3_BONUS_WEIGHT = 0.15

# Mediterranean-pattern steer for the same fatty_liver cohort (EASL/DietMed
# 2024): promote legumes (target ≥3 servings/week) and demote red meat
# (target ≤1/week). Ranking-level nudge on top of the Layer 1 safety gate and
# the omega-3 bonus — not a hard weekly quota. Condition-scoped: inert for
# everyone else. Uses catalog tags (`legumes`, `beef`, `pork`).
_LEGUME_TAG = "legumes"
_RED_MEAT_TAGS = frozenset({"beef", "pork"})
_LEGUME_BONUS_WEIGHT = 0.10
_RED_MEAT_PENALTY_WEIGHT = 0.20
# High glycemic-load penalty for the same fatty_liver cohort — targets the
# refined-carb/fructose load MASLD guidance limits. Uses recipes.gl (94% pop).
_GL_PENALTY_WEIGHT = 0.15


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
        embedding_cache: dict[
            UUID,
            tuple[list[str], int | None, int | None, list[str], float | None, list[float]],
        ]
        | None = None,
    ) -> list[tuple[UUID, float]]:
        if not candidate_ids:
            return []
        # Use pre-fetched context if provided (avoids per-slot DB roundtrip).
        if ranking_context is None:
            ranking_context = await self.profile_ctx.get_ranking_context(user_id)
        country = (ranking_context.get("country") or "").lower() or None
        prep_pref = ranking_context.get("prep_time_pref_min")
        conditions = ranking_context.get("conditions") or []
        promote_omega3 = bool(_OMEGA3_PROMOTE_CONDITIONS.intersection(conditions))

        _SQL = text(
            """
            SELECT id, regions, prep_min, omega3_mg, tags, gl, embedding
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
                        row["omega3_mg"],
                        list(row["tags"] or []),
                        float(row["gl"]) if row["gl"] is not None else None,
                        list(row["embedding"]) if row["embedding"] is not None else [],
                    )
            rows = [
                {"id": cid,
                 "regions": embedding_cache[cid][0],
                 "prep_min": embedding_cache[cid][1],
                 "omega3_mg": embedding_cache[cid][2],
                 "tags": embedding_cache[cid][3],
                 "gl": embedding_cache[cid][4],
                 "embedding": embedding_cache[cid][5]}
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
            # Condition-scoped omega-3 promotion (e.g. fatty_liver): additive
            # bonus so oily-fish recipes surface into the plan. Never a penalty
            # for low/unknown omega-3, and inert for users without the
            # condition (promote_omega3 is False → no change to prior ranking).
            if promote_omega3:
                total += _OMEGA3_BONUS_WEIGHT * omega3_fit(r["omega3_mg"])
                # Mediterranean-pattern steer (same fatty_liver cohort):
                # lift legume dishes, push red-meat dishes down. Nudge, not a
                # hard weekly quota — measured post-deploy (see PRD).
                _tags = set(r["tags"] or [])
                if _LEGUME_TAG in _tags:
                    total += _LEGUME_BONUS_WEIGHT
                if _RED_MEAT_TAGS & _tags:
                    total -= _RED_MEAT_PENALTY_WEIGHT
                # Push down high glycemic-load dishes (refined carbs / fructose).
                total -= _GL_PENALTY_WEIGHT * gl_penalty(r["gl"])
            scored.append((rid, total))
        # Stable tie-break by id: equal scores must rank identically
        # across runs for seeded reproducibility.
        scored.sort(key=lambda x: (-x[1], str(x[0])))
        return scored
