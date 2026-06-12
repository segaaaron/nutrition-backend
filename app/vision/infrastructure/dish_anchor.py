"""SqlDishAnchor — top-down kcal anchor from the NOVA recipe catalog.

Looks up a detected main-dish name against `recipes` via pg_trgm
similarity (name_en + Spanish translation), returning the recipe's kcal
and its total component grams so the triangulation arbiter can scale it
to the estimated portion. Read-only, single query, best-effort.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.vision.domain.triangulation import MIN_ANCHOR_SIMILARITY, DishAnchor

log = get_logger("vision.dish_anchor")

_SQL = text(
    """
    SELECT r.kcal,
           COALESCE(SUM(rc.amount_g), 0) AS grams,
           GREATEST(
               similarity(lower(r.name_en), :n),
               similarity(lower(COALESCE(r.name_translations->>'es', '')), :n)
           ) AS sim
      FROM recipes r
      LEFT JOIN recipe_components rc ON rc.recipe_id = r.id
     WHERE r.kcal IS NOT NULL
       AND (
           similarity(lower(r.name_en), :n) > :min_sim
           OR similarity(lower(COALESCE(r.name_translations->>'es', '')), :n) > :min_sim
       )
     GROUP BY r.id
     ORDER BY sim DESC
     LIMIT 1
    """
)


class SqlDishAnchor:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def lookup(self, name: str) -> DishAnchor | None:
        try:
            row = (
                await self.s.execute(
                    _SQL,
                    {"n": name.lower().strip()[:120], "min_sim": MIN_ANCHOR_SIMILARITY},
                )
            ).first()
        except Exception as exc:  # noqa: BLE001 — OK4: anchor is a best-effort second opinion; lookup failure must not fail the photo job
            log.warning("dish_anchor.lookup_failed", err=str(exc))
            return None
        if row is None or row[0] is None:
            return None
        return DishAnchor(
            recipe_kcal=int(row[0]),
            recipe_grams=float(row[1] or 0),
            similarity=float(row[2]),
        )
