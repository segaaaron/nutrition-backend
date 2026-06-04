"""Food log repository: query, soft-delete (audit), daily totals + trends.

The current food_logs schema has no `deleted_at` column; soft-delete is
achieved by appending an entry to `audit_log` and physically deleting the row.
Restoration is out of scope (immutability of nutrition history is preferred
once N days have elapsed — see backup procedure).
"""

from __future__ import annotations

import base64
import json
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.tracking.domain.food_log import (
    DailyTotals,
    FoodLog,
    FoodLogSearchQuery,
)


def _encode_cursor(created_at: datetime, log_id: UUID) -> str:
    raw = json.dumps({"t": created_at.isoformat(), "id": str(log_id)})
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    raw = base64.urlsafe_b64decode(cursor.encode()).decode()
    obj = json.loads(raw)
    return datetime.fromisoformat(obj["t"]), UUID(obj["id"])


class SqlFoodLogRepository:
    """Read-side + delete for food_logs. Writes happen in the vision pipeline."""

    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def search(self, q: FoodLogSearchQuery) -> tuple[list[FoodLog], str | None]:
        params: dict = {"uid": str(q.user_id), "limit": min(q.limit, 200) + 1}
        clauses = ["user_id = :uid"]
        if q.date_from:
            clauses.append("date >= :df")
            params["df"] = q.date_from
        if q.date_to:
            clauses.append("date <= :dt")
            params["dt"] = q.date_to
        if q.meal_time:
            clauses.append("meal_time = :mt")
            params["mt"] = q.meal_time
        if q.method:
            clauses.append("method = :m")
            params["m"] = q.method
        if q.cursor:
            t, lid = _decode_cursor(q.cursor)
            clauses.append("(created_at, id) < (:ct, :cid)")
            params["ct"] = t
            params["cid"] = str(lid)

        where = " AND ".join(clauses)
        # S608 noqa: `clauses` is assembled exclusively from literal WHERE
        # fragments authored in this function. All values bound via :params.
        sql = text(
            f"""
            SELECT id, user_id, date, meal_time, method, food_id, recipe_id,
                   free_text_name, amount_g, kcal, protein_g, carbs_g, fat_g,
                   confidence, source_image_url, created_at
              FROM food_logs
             WHERE {where}
             ORDER BY created_at DESC, id DESC
             LIMIT :limit
        """
        )  # noqa: S608
        rows = (await self.s.execute(sql, params)).mappings().all()
        next_cursor: str | None = None
        if len(rows) > q.limit:
            rows = rows[: q.limit]
            last = rows[-1]
            next_cursor = _encode_cursor(last["created_at"], last["id"])
        out = [
            FoodLog(
                id=r["id"],
                user_id=r["user_id"],
                date=r["date"],
                meal_time=r["meal_time"],
                method=r["method"],
                food_id=r["food_id"],
                recipe_id=r["recipe_id"],
                free_text_name=r["free_text_name"],
                amount_g=r["amount_g"],
                kcal=r["kcal"],
                protein_g=r["protein_g"],
                carbs_g=r["carbs_g"],
                fat_g=r["fat_g"],
                confidence=r["confidence"],
                source_image_url=r["source_image_url"],
                created_at=r["created_at"],
            )
            for r in rows
        ]
        return out, next_cursor

    async def delete(self, *, user_id: UUID, log_id: UUID, reason: str | None) -> None:
        row = (
            await self.s.execute(
                text("SELECT id FROM food_logs WHERE id = :id AND user_id = :uid"),
                {"id": str(log_id), "uid": str(user_id)},
            )
        ).first()
        if row is None:
            raise NotFoundError(detail="food_log_not_found")
        await self.s.execute(
            text(
                """
                INSERT INTO audit_log (actor_type, actor_id, action, target, payload)
                VALUES ('user', :uid, 'food_log.delete', :tid, :payload::jsonb)
            """
            ),
            {
                "uid": str(user_id),
                "tid": str(log_id),
                "payload": json.dumps({"reason": reason or ""}),
            },
        )
        await self.s.execute(text("DELETE FROM food_logs WHERE id = :id"), {"id": str(log_id)})

    async def daily_totals(
        self,
        *,
        user_id: UUID,
        on: date,
    ) -> DailyTotals:
        # Prefer the daily continuous aggregate (added in migration 0004) when
        # it exists; fall back to a per-row sum otherwise.
        sql_agg = text(
            """
            SELECT day, kcal, protein_g, carbs_g, fat_g
              FROM food_logs_aggregates_daily
             WHERE user_id = :uid AND day = :d
        """
        )
        try:
            r = (await self.s.execute(sql_agg, {"uid": str(user_id), "d": on})).mappings().first()
            if r:
                # Fiber/sugar/sodium are NOT in the continuous aggregate
                # (kept narrow to bound storage). Fetch them via a quick scan.
                extras = (
                    (
                        await self.s.execute(
                            text(
                                """
                    SELECT
                      COALESCE(SUM(CASE WHEN f.fiber_g IS NOT NULL
                                        THEN (f.fiber_g * COALESCE(fl.amount_g,100) / 100.0) END),0)::int AS fiber_g,
                      COALESCE(SUM(CASE WHEN f.sugar_g IS NOT NULL
                                        THEN (f.sugar_g * COALESCE(fl.amount_g,100) / 100.0) END),0)::int AS sugar_g,
                      COALESCE(SUM(CASE WHEN f.sodium_mg IS NOT NULL
                                        THEN (f.sodium_mg * COALESCE(fl.amount_g,100) / 100.0) END),0)::int AS sodium_mg
                      FROM food_logs fl
                      LEFT JOIN foods f ON f.id = fl.food_id
                     WHERE fl.user_id = :uid AND fl.date = :d
                """
                            ),
                            {"uid": str(user_id), "d": on},
                        )
                    )
                    .mappings()
                    .first()
                    or {}
                )
                return DailyTotals(
                    date=on,
                    kcal=int(r["kcal"] or 0),
                    protein_g=int(r["protein_g"] or 0),
                    carbs_g=int(r["carbs_g"] or 0),
                    fat_g=int(r["fat_g"] or 0),
                    fiber_g=int(extras.get("fiber_g") or 0),
                    sugar_g=int(extras.get("sugar_g") or 0),
                    sodium_mg=int(extras.get("sodium_mg") or 0),
                )
        except Exception:  # noqa: BLE001,S110 — aggregate may not exist yet (falls through)
            pass

        sql = text(
            """
            SELECT
              COALESCE(SUM(fl.kcal),0)::int      AS kcal,
              COALESCE(SUM(fl.protein_g),0)::int AS protein_g,
              COALESCE(SUM(fl.carbs_g),0)::int   AS carbs_g,
              COALESCE(SUM(fl.fat_g),0)::int     AS fat_g,
              COALESCE(SUM(CASE WHEN f.fiber_g IS NOT NULL
                                THEN (f.fiber_g * COALESCE(fl.amount_g,100) / 100.0) END),0)::int AS fiber_g,
              COALESCE(SUM(CASE WHEN f.sugar_g IS NOT NULL
                                THEN (f.sugar_g * COALESCE(fl.amount_g,100) / 100.0) END),0)::int AS sugar_g,
              COALESCE(SUM(CASE WHEN f.sodium_mg IS NOT NULL
                                THEN (f.sodium_mg * COALESCE(fl.amount_g,100) / 100.0) END),0)::int AS sodium_mg
              FROM food_logs fl
              LEFT JOIN foods f ON f.id = fl.food_id
             WHERE fl.user_id = :uid AND fl.date = :d
        """
        )
        r = (await self.s.execute(sql, {"uid": str(user_id), "d": on})).mappings().first() or {}
        return DailyTotals(
            date=on,
            kcal=int(r.get("kcal") or 0),
            protein_g=int(r.get("protein_g") or 0),
            carbs_g=int(r.get("carbs_g") or 0),
            fat_g=int(r.get("fat_g") or 0),
            fiber_g=int(r.get("fiber_g") or 0),
            sugar_g=int(r.get("sugar_g") or 0),
            sodium_mg=int(r.get("sodium_mg") or 0),
        )

    async def trend(
        self,
        *,
        user_id: UUID,
        window_days: int,
    ) -> list[dict]:
        sql = text(
            """
            SELECT day, kcal, protein_g, carbs_g, fat_g
              FROM food_logs_aggregates_daily
             WHERE user_id = :uid AND day >= (CURRENT_DATE - (:n || ' days')::interval)
             ORDER BY day ASC
        """
        )
        try:
            rows = (
                (await self.s.execute(sql, {"uid": str(user_id), "n": window_days}))
                .mappings()
                .all()
            )
            if rows:
                return [dict(r) for r in rows]
        except Exception:  # noqa: BLE001,S110 — aggregate table optional; fallback below
            pass
        # Fallback raw aggregation per date.
        sql2 = text(
            """
            SELECT date AS day,
                   COALESCE(SUM(kcal),0)::int      AS kcal,
                   COALESCE(SUM(protein_g),0)::int AS protein_g,
                   COALESCE(SUM(carbs_g),0)::int   AS carbs_g,
                   COALESCE(SUM(fat_g),0)::int     AS fat_g
              FROM food_logs
             WHERE user_id = :uid
               AND date >= (CURRENT_DATE - (:n || ' days')::interval)::date
             GROUP BY date
             ORDER BY date ASC
        """
        )
        rows = (
            (await self.s.execute(sql2, {"uid": str(user_id), "n": window_days})).mappings().all()
        )
        return [dict(r) for r in rows]

    async def micros_today(self, *, user_id: UUID) -> dict[str, float]:
        """Sum micronutrient JSONB across today's logged foods.

        Each foods.micronutrients is e.g. {"calcium_mg": 120, "iron_mg": 2.4}.
        Scaling: micros are per-100g; multiply by amount_g/100.

        CLAUDE.md non-negotiable #2 — Decimal + ROUND_HALF_EVEN (banker's
        rounding, IEEE 754-2008 default) for nutrition macro/micro math.
        Float arithmetic is forbidden in nutrition numbers. We accumulate
        in Decimal, quantize at 4 decimal places, and cast to float only
        at the API boundary (response is JSON-serialisable).
        """
        from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation

        sql = text(
            """
            SELECT fl.amount_g, f.micronutrients
              FROM food_logs fl
              JOIN foods f ON f.id = fl.food_id
             WHERE fl.user_id = :uid AND fl.date = CURRENT_DATE
               AND f.micronutrients IS NOT NULL
        """
        )
        rows = (await self.s.execute(sql, {"uid": str(user_id)})).all()
        totals: dict[str, Decimal] = {}
        q = Decimal("0.0001")
        for amount_g, micros in rows:
            try:
                scale = Decimal(str(amount_g if amount_g is not None else 100)) / Decimal("100")
            except (InvalidOperation, TypeError, ValueError):
                continue
            for k, v in (micros or {}).items():
                try:
                    increment = (Decimal(str(v)) * scale).quantize(
                        q,
                        rounding=ROUND_HALF_EVEN,
                    )
                    totals[k] = (totals.get(k, Decimal("0")) + increment).quantize(
                        q,
                        rounding=ROUND_HALF_EVEN,
                    )
                except (InvalidOperation, TypeError, ValueError):
                    continue
        # Float cast only at the API boundary — values already quantized.
        return {k: float(v) for k, v in totals.items()}
