"""Adapter that retrieves recent completed-meal embeddings + onboarding centroid."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.domain.time import utc_today


class SqlEmbeddingFetcher:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def get_user_completed_embeddings(
        self, user_id: UUID, weeks_back: int = 8
    ) -> list[tuple[int, list[float]]]:
        # Pull completed plan meals from the last `weeks_back` weeks with
        # their recipe embedding. We compute weeks-ago in Python from
        # plan_days.date to keep the SQL portable.
        sql = text(
            """
            SELECT pd.date AS d, r.embedding AS emb
              FROM plan_meals pm
              JOIN plan_days pd ON pd.id = pm.plan_day_id
              JOIN plans p ON p.id = pd.plan_id
              JOIN recipes r ON r.id = pm.recipe_id
             WHERE p.user_id = :uid
               AND pm.completed = true
               AND pd.date >= (CURRENT_DATE - (:weeks * 7))
               AND r.embedding IS NOT NULL
             ORDER BY pd.date DESC
             LIMIT 50
        """
        )
        res = await self.s.execute(sql, {"uid": str(user_id), "weeks": weeks_back})
        out: list[tuple[int, list[float]]] = []

        today = utc_today()
        for row in res.mappings():
            weeks_ago = max(0, (today - row["d"]).days // 7)
            out.append((weeks_ago, list(row["emb"])))
        return out

    async def get_onboarding_centroid(self, user_id: UUID) -> list[float] | None:
        # Compute centroid of recipes matching the user's preference tags.
        sql = text(
            """
            SELECT AVG(r.embedding) AS centroid
              FROM recipes r
             WHERE r.embedding IS NOT NULL
               AND r.tags && (
                   SELECT COALESCE(preferences, '{}'::text[])
                     FROM plans WHERE user_id = :uid
                  ORDER BY created_at DESC LIMIT 1
               )
        """
        )
        try:
            res = await self.s.execute(sql, {"uid": str(user_id)})
            row = res.first()
            if row and row[0] is not None:
                return list(row[0])
        except Exception:  # noqa: BLE001
            return None
        return None
