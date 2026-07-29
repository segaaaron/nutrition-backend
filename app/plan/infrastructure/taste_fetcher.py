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
        # Cold-start centroid: average embedding of recipes that match the user's
        # declared goal (target_goals) and/or region, so new users get a
        # meaningful taste signal instead of a zero vector.
        # Falls back to plan preferences (old behavior) when goal+region yield nothing.
        sql = text(
            """
            WITH profile AS (
                SELECT COALESCE(goal::text, '')  AS goal,
                       COALESCE(region,    '')   AS region
                  FROM user_profiles
                 WHERE user_id = :uid
            ),
            plan_prefs AS (
                SELECT COALESCE(preferences, '{}'::text[]) AS tags
                  FROM plans
                 WHERE user_id = :uid
                 ORDER BY created_at DESC
                 LIMIT 1
            )
            SELECT AVG(r.embedding) AS centroid
              FROM recipes r, profile
             WHERE r.embedding IS NOT NULL
               AND r.quarantined_at IS NULL
               AND (
                   (profile.goal    <> '' AND profile.goal    = ANY(CAST(r.target_goals AS text[])))
                OR (profile.region  <> '' AND r.regions && CAST(ARRAY[profile.region] AS char(5)[]))
                OR r.tags && (SELECT tags FROM plan_prefs)
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
