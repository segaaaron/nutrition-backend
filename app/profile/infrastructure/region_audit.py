"""SQL adapter for the profile-region-change audit port.

Patrón #3 (session lifecycle): this adapter runs on the SAME
``AsyncSession`` as the profile upsert, so the audit row and the
profile mutation commit (or roll back) atomically. The previous
implementation opened a nested ``session_scope()`` which committed
independently — creating orphan audit rows when the outer transaction
rolled back, and audit lies when the audit committed but the outer
later raised. Both compromised the 30-day region-lock spoof-proofing
audit (ADR-0026 L1).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import text as _sql_text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(slots=True)
class SqlRegionAudit:
    """Reads + writes ``profile_region_change_audit`` on the bound session."""

    session: AsyncSession

    async def last_change_at(self, user_id: UUID) -> datetime | None:
        row = (
            await self.session.execute(
                _sql_text(
                    """
                    SELECT changed_at FROM profile_region_change_audit
                     WHERE user_id = :uid
                     ORDER BY changed_at DESC LIMIT 1
                    """
                ),
                {"uid": str(user_id)},
            )
        ).scalar()
        return row

    async def record_change(
        self,
        *,
        user_id: UUID,
        old_region: str | None,
        new_region: str | None,
        changed_at: datetime,
    ) -> None:
        await self.session.execute(
            _sql_text(
                """
                INSERT INTO profile_region_change_audit
                    (user_id, old_region, new_region, changed_at)
                VALUES (:uid, :old, :new, :ts)
                """
            ),
            {
                "uid": str(user_id),
                "old": old_region,
                "new": new_region,
                "ts": changed_at,
            },
        )
