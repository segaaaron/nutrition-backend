"""Fasting session SQL repository."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.tracking.domain.fasting import FastingPreference, FastingSession


def _enc(t: datetime, sid: UUID) -> str:
    return base64.urlsafe_b64encode(
        json.dumps({"t": t.isoformat(), "id": str(sid)}).encode()
    ).decode()


def _dec(c: str) -> tuple[datetime, UUID]:
    obj = json.loads(base64.urlsafe_b64decode(c.encode()).decode())
    return datetime.fromisoformat(obj["t"]), UUID(obj["id"])


def _row_to_entity(r) -> FastingSession:
    return FastingSession(
        id=r["id"],
        user_id=r["user_id"],
        method_h=r["method_h"],
        start_ts=r["start_ts"],
        end_ts=r["end_ts"],
        duration_s=r["duration_s"],
        target_s=r["target_s"],
        achieved=r["achieved"],
        protocol=r.get("protocol"),
        break_reason=r.get("break_reason"),
    )


def _row_to_preference(r) -> FastingPreference:
    return FastingPreference(
        user_id=r["user_id"],
        enabled=bool(r["enabled"]),
        protocol=r["protocol"],
        window_start_local=r["window_start_local"],
        time_zone=r["time_zone"],
        reminders_enabled=bool(r["reminders_enabled"]),
        updated_at=r["updated_at"],
    )


class SqlFastingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def active_for(self, user_id: UUID) -> FastingSession | None:
        sql = text(
            """
            SELECT id, user_id, method_h, start_ts, end_ts, duration_s, target_s, achieved
              FROM fasting_sessions
             WHERE user_id = :uid AND end_ts IS NULL
             ORDER BY start_ts DESC
             LIMIT 1
        """
        )
        r = (await self.s.execute(sql, {"uid": str(user_id)})).mappings().first()
        return _row_to_entity(r) if r else None

    async def get(self, session_id: UUID) -> FastingSession | None:
        sql = text(
            """
            SELECT id, user_id, method_h, start_ts, end_ts, duration_s, target_s, achieved
              FROM fasting_sessions WHERE id = :id
        """
        )
        r = (await self.s.execute(sql, {"id": str(session_id)})).mappings().first()
        return _row_to_entity(r) if r else None

    async def insert(self, fs: FastingSession) -> None:
        await self.s.execute(
            text(
                """
            INSERT INTO fasting_sessions (id, user_id, method_h, start_ts, target_s, protocol)
            VALUES (:id, :uid, :m, :s, :t, :p)
        """
            ),
            {
                "id": str(fs.id),
                "uid": str(fs.user_id),
                "m": fs.method_h,
                "s": fs.start_ts,
                "t": fs.target_s,
                "p": fs.protocol,
            },
        )

    async def insert_log(self, fs: FastingSession) -> None:
        """Direct log insert — stores a completed window without start/stop flow."""
        await self.s.execute(
            text(
                """
            INSERT INTO fasting_sessions
                (id, user_id, method_h, start_ts, end_ts, duration_s, target_s,
                 achieved, protocol, break_reason)
            VALUES (:id, :uid, :m, :s, :e, :d, :t, :a, :p, :br)
        """
            ),
            {
                "id": str(fs.id),
                "uid": str(fs.user_id),
                "m": fs.method_h,
                "s": fs.start_ts,
                "e": fs.end_ts,
                "d": fs.duration_s,
                "t": fs.target_s,
                "a": fs.achieved,
                "p": fs.protocol,
                "br": fs.break_reason,
            },
        )

    async def has_overlapping(
        self,
        user_id: UUID,
        started_at: datetime,
        ended_at: datetime,
        exclude_id: UUID | None = None,
    ) -> bool:
        params: dict = {
            "uid": str(user_id),
            "s": started_at,
            "e": ended_at,
        }
        exclude_clause = "AND id != :excl" if exclude_id else ""
        if exclude_id:
            params["excl"] = str(exclude_id)
        row = (
            await self.s.execute(
                text(
                    f"""
                SELECT EXISTS(
                    SELECT 1 FROM fasting_sessions
                     WHERE user_id = :uid
                       AND start_ts < :e
                       AND COALESCE(end_ts, now()) > :s
                       {exclude_clause}
                )
                """  # noqa: S608
                ),
                params,
            )
        ).scalar()
        return bool(row)

    async def get_preference(self, user_id: UUID) -> FastingPreference | None:
        r = (
            await self.s.execute(
                text(
                    """
            SELECT user_id, enabled, protocol, window_start_local,
                   time_zone, reminders_enabled, updated_at
              FROM user_fasting_preferences WHERE user_id = :uid
        """
                ),
                {"uid": str(user_id)},
            )
        ).mappings().first()
        return _row_to_preference(r) if r else None

    async def upsert_preference(self, pref: FastingPreference) -> FastingPreference:
        now = datetime.now(UTC)
        await self.s.execute(
            text(
                """
            INSERT INTO user_fasting_preferences
                (user_id, enabled, protocol, window_start_local,
                 time_zone, reminders_enabled, updated_at)
            VALUES (:uid, :en, :p, :ws, :tz, :re, :upd)
            ON CONFLICT (user_id) DO UPDATE SET
                enabled            = EXCLUDED.enabled,
                protocol           = EXCLUDED.protocol,
                window_start_local = EXCLUDED.window_start_local,
                time_zone          = EXCLUDED.time_zone,
                reminders_enabled  = EXCLUDED.reminders_enabled,
                updated_at         = EXCLUDED.updated_at
        """
            ),
            {
                "uid": str(pref.user_id),
                "en": pref.enabled,
                "p": pref.protocol,
                "ws": pref.window_start_local,
                "tz": pref.time_zone,
                "re": pref.reminders_enabled,
                "upd": now,
            },
        )
        pref.updated_at = now
        return pref

    async def logs(
        self,
        *,
        user_id: UUID,
        from_date: str | None,
        to_date: str | None,
        cursor: str | None,
        limit: int,
    ) -> tuple[list[FastingSession], str | None]:
        params: dict = {"uid": str(user_id), "limit": limit + 1}
        clauses = ["user_id = :uid", "end_ts IS NOT NULL"]
        if from_date:
            clauses.append("start_ts::date >= :from_d")
            params["from_d"] = from_date
        if to_date:
            clauses.append("start_ts::date <= :to_d")
            params["to_d"] = to_date
        if cursor:
            t, sid = _dec(cursor)
            clauses.append("(start_ts, id) < (:ct, :cid)")
            params["ct"] = t
            params["cid"] = str(sid)
        where = " AND ".join(clauses)
        sql = text(
            f"""
            SELECT id, user_id, method_h, start_ts, end_ts, duration_s, target_s,
                   achieved, protocol, break_reason
              FROM fasting_sessions WHERE {where}
             ORDER BY start_ts DESC, id DESC LIMIT :limit
        """  # noqa: S608
        )
        rows = (await self.s.execute(sql, params)).mappings().all()
        nxt = None
        if len(rows) > limit:
            rows = rows[:limit]
            nxt = _enc(rows[-1]["start_ts"], rows[-1]["id"])
        return [_row_to_entity(r) for r in rows], nxt

    async def streak_days(self, user_id: UUID) -> int:
        """Count consecutive days with ≥1 achieved fasting window.

        Anchors on CURRENT_DATE or CURRENT_DATE-1 so a live streak stays
        visible all day even before today's window closes.
        Only achieved=true windows count; broken fasts are excluded.
        """
        row = (
            await self.s.execute(
                text(
                    """
            WITH logged AS (
                SELECT DISTINCT end_ts::date AS d
                  FROM fasting_sessions
                 WHERE user_id = :uid AND end_ts IS NOT NULL AND achieved = true
            ),
            series AS (
                SELECT d,
                       d - (ROW_NUMBER() OVER (ORDER BY d))::int * INTERVAL '1 day' AS grp
                  FROM logged
            ),
            anchor AS (
                SELECT grp FROM series
                 WHERE d IN (CURRENT_DATE, CURRENT_DATE - 1)
                 ORDER BY d DESC
                 LIMIT 1
            )
            SELECT COUNT(*) AS streak
              FROM series
              JOIN anchor ON series.grp = anchor.grp
        """
                ),
                {"uid": str(user_id)},
            )
        ).mappings().first()
        return int(row["streak"]) if row and row["streak"] else 0

    async def windows_completed_7d(self, user_id: UUID) -> int:
        row = (
            await self.s.execute(
                text(
                    """
            SELECT COUNT(*)::int AS cnt
              FROM fasting_sessions
             WHERE user_id = :uid
               AND end_ts IS NOT NULL
               AND achieved = true
               AND end_ts >= CURRENT_DATE - 6
        """
                ),
                {"uid": str(user_id)},
            )
        ).scalar()
        return int(row or 0)

    async def finalize(self, fs: FastingSession) -> None:
        await self.s.execute(
            text(
                """
            UPDATE fasting_sessions
               SET end_ts = :e, duration_s = :d, achieved = :a
             WHERE id = :id
        """
            ),
            {
                "id": str(fs.id),
                "e": fs.end_ts,
                "d": fs.duration_s,
                "a": fs.achieved,
            },
        )

    async def history(
        self,
        *,
        user_id: UUID,
        cursor: str | None,
        limit: int,
    ) -> tuple[list[FastingSession], str | None]:
        params: dict = {"uid": str(user_id), "limit": limit + 1}
        clauses = ["user_id = :uid"]
        if cursor:
            t, sid = _dec(cursor)
            clauses.append("(start_ts, id) < (:ct, :cid)")
            params["ct"] = t
            params["cid"] = str(sid)
        where = " AND ".join(clauses)
        # S608 noqa: `clauses` is assembled exclusively from literal WHERE
        # fragments authored in this function ("user_id = :uid", cursor
        # comparison). All values bound via :params.
        sql = text(
            f"""
            SELECT id, user_id, method_h, start_ts, end_ts, duration_s, target_s, achieved
              FROM fasting_sessions WHERE {where}
             ORDER BY start_ts DESC, id DESC LIMIT :limit
        """  # noqa: S608 — `where` from literal clauses only; values bound
        )
        rows = (await self.s.execute(sql, params)).mappings().all()
        nxt = None
        if len(rows) > limit:
            rows = rows[:limit]
            nxt = _enc(rows[-1]["start_ts"], rows[-1]["id"])
        return [_row_to_entity(r) for r in rows], nxt


def new_session_id() -> UUID:
    return uuid4()
