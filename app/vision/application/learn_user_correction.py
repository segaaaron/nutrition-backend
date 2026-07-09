"""When the user edits a detected item, upsert vision_user_corrections so
future matches resolve instantly without LLM/embedding lookup.

Also:
- Logs to vision_accuracy_log for precision tracking (F6.1).
- Updates user_portion_calibration with the corrected/estimated ratio (F3.1).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

log = get_logger("vision.learn")


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
        match_method: str | None = None,
    ) -> None:
        await self.session.execute(
            text(
                """
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
        """
            ),
            {
                "uid": str(user_id),
                "n": _norm(detected_name),
                "fid": str(corrected_food_id) if corrected_food_id else None,
                "ag": float(corrected_amount_g) if corrected_amount_g is not None else None,
            },
        )

        # F3.1 + F6.1: look up the original food_log for this user+name to
        # compute the correction ratio and accuracy delta.
        await self._update_calibration_and_accuracy(
            user_id=user_id,
            detected_name=detected_name,
            corrected_amount_g=corrected_amount_g,
            match_method=match_method,
        )

    async def _update_calibration_and_accuracy(
        self,
        *,
        user_id: UUID,
        detected_name: str,
        corrected_amount_g: Decimal | None,
        match_method: str | None = None,
    ) -> None:
        """Best-effort — any failure must not break the correction flow."""
        try:
            # Fetch the most recent food_log for this user+food name to get
            # the original detected amount, kcal, and food_group.
            row = (
                await self.session.execute(
                    text(
                        """
                        SELECT fl.amount_g, fl.kcal, f.food_group
                          FROM food_logs fl
                          LEFT JOIN foods f ON f.id = fl.food_id
                         WHERE fl.user_id = :uid
                           AND (
                               fl.free_text_name ILIKE :name_like
                               OR f.name_norm = :name_norm
                           )
                         ORDER BY fl.created_at DESC
                         LIMIT 1
                        """
                    ),
                    {
                        "uid": str(user_id),
                        "name_like": f"%{detected_name[:60]}%",
                        "name_norm": _norm(detected_name),
                    },
                )
            ).first()

            if row is None:
                return

            original_g = float(row[0]) if row[0] else None
            original_kcal = int(row[1]) if row[1] else None
            food_group = str(row[2]) if row[2] else None

            # F3.1: update portion calibration ratio for this food_group.
            if (
                original_g
                and corrected_amount_g is not None
                and float(corrected_amount_g) > 0
                and food_group
            ):
                ratio = float(corrected_amount_g) / original_g
                if 0.1 <= ratio <= 10.0:
                    await self.session.execute(
                        text(
                            """
                            INSERT INTO user_portion_calibration
                                (user_id, food_group, correction_ratio, sample_count, updated_at)
                            VALUES (:uid, :fg, :r, 1, now())
                            ON CONFLICT (user_id, food_group) DO UPDATE
                              SET correction_ratio = (
                                    user_portion_calibration.correction_ratio
                                    * user_portion_calibration.sample_count + :r
                                  ) / (user_portion_calibration.sample_count + 1),
                                  sample_count = user_portion_calibration.sample_count + 1,
                                  updated_at = now()
                            """
                        ),
                        {"uid": str(user_id), "fg": food_group, "r": ratio},
                    )

            # F6.1: log the accuracy delta for ops observability.
            corrected_kcal: int | None = None
            if original_kcal and original_g and corrected_amount_g and float(corrected_amount_g) > 0:
                corrected_kcal = round(original_kcal * float(corrected_amount_g) / original_g)

            error_pct: float | None = None
            if original_kcal and corrected_kcal and original_kcal > 0:
                error_pct = round((corrected_kcal - original_kcal) / original_kcal * 100, 2)

            await self.session.execute(
                text(
                    """
                    INSERT INTO vision_accuracy_log
                        (user_id, food_group, match_method,
                         kcal_detected, kcal_corrected, error_pct, created_at)
                    VALUES (:uid, :fg, :mm, :kd, :kc, :ep, now())
                    """
                ),
                {
                    "uid": str(user_id),
                    "fg": food_group,
                    "mm": match_method,
                    "kd": original_kcal,
                    "kc": corrected_kcal,
                    "ep": error_pct,
                },
            )

        except Exception as exc:  # noqa: BLE001
            log.warning("vision.learn.calibration_failed", err=str(exc)[:200])
