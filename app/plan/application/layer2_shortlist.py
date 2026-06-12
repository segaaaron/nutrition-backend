"""Layer 2 — Macro-balanced shortlist (SQL/Python knapsack-lite).

Inputs from Layer 1: `candidate_ids` already region/allergen/condition safe.

Per slot, fetch macro metadata once, rank by a normalised weighted score:

    kcal_fit    = max(0, 1 - |recipe.kcal - target_kcal_share| / target_kcal_share)
    protein_fit = min(1, recipe.protein_g / target_protein_share)
    score       = 0.7 * kcal_fit + 0.3 * protein_fit

Both terms live in [0, 1] so the weights mean what they say. The previous
formula (`-kcal_dev + 0.1 * protein_ratio`) mixed raw kcal units (hundreds)
with a ≤0.2 protein bonus, so protein was decimal noise and the daily
protein goal was effectively ignored (spec §6).

Repetition cap: caller passes `forbidden_ids` containing recipes already
present in the rolling 7-day window (spec §9.5 step 5). We filter those out
before scoring so the next call can re-use the same candidate pool without
manual book-keeping.

Returns top-K `(recipe_id, score)` tuples sorted DESC. Budget: <200 ms.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(slots=True)
class Layer2Shortlist:
    session: AsyncSession

    async def __call__(
        self,
        *,
        candidate_ids: list[UUID],
        meal_time: str,
        kcal_target_share: int,
        protein_target_share: int,
        forbidden_ids: set[UUID],
        top_k: int = 20,
    ) -> list[tuple[UUID, float]]:
        if not candidate_ids:
            return []
        filtered = [cid for cid in candidate_ids if cid not in forbidden_ids]
        if not filtered:
            return []

        sql = text(
            """
            SELECT id, COALESCE(kcal, 0) AS kcal, COALESCE(protein_g, 0) AS protein_g
              FROM recipes
             WHERE id = ANY(CAST(:ids AS uuid[]))
               AND (meal_time IS NULL OR meal_time = :meal_time)
        """
        )
        res = await self.session.execute(
            sql, {"ids": [str(i) for i in filtered], "meal_time": meal_time}
        )
        target_p = max(1, protein_target_share)
        target_k = max(1, kcal_target_share)
        scored: list[tuple[UUID, float]] = []
        for row in res.mappings():
            kcal_dev = abs(int(row["kcal"]) - kcal_target_share)
            kcal_fit = max(0.0, 1.0 - kcal_dev / target_k)
            protein_fit = min(1.0, int(row["protein_g"]) / target_p)
            scored.append((row["id"], 0.7 * kcal_fit + 0.3 * protein_fit))

        # Stable tie-break by id: equal scores must rank identically
        # across runs for seeded reproducibility.
        scored.sort(key=lambda x: (-x[1], str(x[0])))
        return scored[:top_k]
