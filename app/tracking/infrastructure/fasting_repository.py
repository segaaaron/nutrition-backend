"""Fasting session SQL repository."""

from __future__ import annotations

import base64
import json
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.tracking.domain.fasting import FastingSession


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
            INSERT INTO fasting_sessions (id, user_id, method_h, start_ts, target_s)
            VALUES (:id, :uid, :m, :s, :t)
        """
            ),
            {
                "id": str(fs.id),
                "uid": str(fs.user_id),
                "m": fs.method_h,
                "s": fs.start_ts,
                "t": fs.target_s,
            },
        )

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
        """
        )  # noqa: S608
        rows = (await self.s.execute(sql, params)).mappings().all()
        nxt = None
        if len(rows) > limit:
            rows = rows[:limit]
            nxt = _enc(rows[-1]["start_ts"], rows[-1]["id"])
        return [_row_to_entity(r) for r in rows], nxt


def new_session_id() -> UUID:
    return uuid4()
