"""Coach feature D — substitution intelligence.

Given a plan_meal_id + a free-text "why" (e.g., "no me gusta el pescado"),
generate a swap proposal. Cheap deterministic flow: query layer2-style
shortlist of compatible recipes filtered by meal_time + region + non-
contraindicated, ranked by embedding similarity to the current recipe.
Falls back to L4 coherence LLM only if requested.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError


@dataclass(slots=True)
class ProposeSwap:
    session: AsyncSession

    async def __call__(
        self,
        *,
        user_id: UUID,
        plan_meal_id: UUID,
        top_k: int = 3,
    ) -> list[dict]:
        # Get the current meal + recipe + the user's region.
        row = (
            await self.session.execute(
                text(
                    """
            SELECT pm.meal_time, pm.recipe_id::text, up.region, up.allergies
              FROM plan_meals pm
              JOIN plan_days pd ON pd.id = pm.plan_day_id
              JOIN plans p ON p.id = pd.plan_id
              JOIN user_profiles up ON up.user_id = p.user_id
             WHERE pm.id = :pmid AND p.user_id = :uid
        """
                ),
                {"pmid": str(plan_meal_id), "uid": str(user_id)},
            )
        ).first()
        if not row:
            raise NotFoundError(f"plan_meal:{plan_meal_id}")
        meal_time, current_recipe_id, region, allergies = row
        allergies = allergies or []

        # Rank alternatives by embedding distance to current recipe.
        rows = (
            await self.session.execute(
                text(
                    """
            WITH cur AS (
                SELECT embedding FROM recipes WHERE id = :rid AND embedding IS NOT NULL
            )
            SELECT r.id::text, r.name_en, r.kcal, r.protein_g,
                   r.embedding <=> (SELECT embedding FROM cur) AS dist
              FROM recipes r, cur
             WHERE r.id != :rid
               AND r.meal_time = :mt
               AND r.regions && ARRAY[:reg]::char(5)[]
               AND NOT (r.allergens && CAST(:al AS allergen_enum[]))
             ORDER BY dist ASC
             LIMIT :k
        """
                ),
                {
                    "rid": current_recipe_id,
                    "mt": meal_time,
                    "reg": region,
                    "al": "{" + ",".join(allergies) + "}",
                    "k": top_k,
                },
            )
        ).all()
        return [
            {
                "recipe_id": r[0],
                "name_en": r[1],
                "kcal": r[2],
                "protein_g": r[3],
                "distance": float(r[4]),
            }
            for r in rows
        ]
