"""When the user edits a detected item, upsert vision_user_corrections so
future matches resolve instantly without LLM/embedding lookup.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


@dataclass(slots=True)
class LearnUserCorrection:
    session: AsyncSession

    async def __call__(
        self,
        *,
        user_id: UUID,
        detected_name: str,
        corrected_food_id: UUID | None,
        corrected_amount_g: Decimal | None,
    ) -> None:
        await self.session.execute(text("""
            INSERT INTO vision_user_corrections (
                user_id, detected_name_norm, corrected_food_id,
                corrected_amount_g, occurrences, last_seen_at
            ) VALUES (
                :uid, :n, :fid, :ag, 1, now()
            )
            ON CONFLICT (user_id, detected_name_norm) DO UPDATE
              SET corrected_food_id = EXCLUDED.corrected_food_id,
                  corrected_amount_g = EXCLUDED.corrected_amount_g,
                  occurrences = vision_user_corrections.occurrences + 1,
                  last_seen_at = now()
        """), {
            "uid": str(user_id),
            "n": _norm(detected_name),
            "fid": str(corrected_food_id) if corrected_food_id else None,
            "ag": float(corrected_amount_g) if corrected_amount_g is not None else None,
        })
