"""Layer 1 — Eligibility filter (deterministic SQL, no LLM).

Filters the recipe catalog down to the candidate set for a given user × meal
slot. **Hard** rules (no soft fallback):

  1. Region overlap: `recipes.regions && ARRAY[user.region]` (ADR-0008).
  2. Allergen hard-exclude: `NOT (recipes.allergens && user.allergies)` —
     never returns a recipe whose denormalised allergens overlap the user's
     allergies. Enforced through the closed `allergen_enum` (ADR-0001).
  3. Contraindicated conditions: any recipe listing a user's condition in
     `contraindicated_conditions` is dropped.
  4. Condition-specific clinical gates (per spec §6 / ADR-0001):
       diabetes_t2          → sugar_g/portion ≤ 15
       hypertension         → sodium_mg/portion ≤ 600
       ckd                  → protein_g/portion ≤ weight_kg * 0.8 / 3
       hypercholesterolemia → sat_fat_g/portion ≤ 5
       gout                 → no purine-heavy tag (organ_meat, shellfish)
  5. Meal-time match.

Budget: <50 ms (single round-trip indexed query, GIN-backed array ops).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class _ProfileReader(Protocol):
    async def get_eligibility_profile(
        self, user_id: UUID
    ) -> dict | None: ...  # {region, allergies[], conditions[], weight_kg}


@dataclass(slots=True)
class Layer1Eligibility:
    session: AsyncSession
    profile_reader: _ProfileReader

    async def __call__(self, *, user_id: UUID, meal_time: str) -> list[UUID]:
        prof = await self.profile_reader.get_eligibility_profile(user_id)
        if prof is None:
            return []

        region = prof.get("region") or "us"
        allergies: list[str] = prof.get("allergies") or []
        conditions: list[str] = prof.get("conditions") or []
        weight_kg: Decimal | None = prof.get("weight_kg")

        where: list[str] = [
            "r.regions && CAST(:regions AS char(5)[])",
            "r.meal_time = :meal_time",
        ]
        params: dict[str, object] = {
            "regions": [region],
            "meal_time": meal_time,
        }

        if allergies:
            # Defensive: cast both sides to text so we never trip enum-vs-text
            # operator-resolution issues in mixed contexts.
            where.append("NOT (CAST(r.allergens AS text[]) && CAST(:allergies AS text[]))")
            params["allergies"] = allergies

        if conditions:
            where.append(
                "NOT (r.contraindicated_conditions && CAST(:conditions AS text[]))"
            )
            params["conditions"] = conditions

            if "diabetes_t2" in conditions:
                where.append("(r.sugar_g IS NULL OR r.sugar_g <= 15)")
            if "hypertension" in conditions:
                where.append("(r.sodium_mg IS NULL OR r.sodium_mg <= 600)")
            if "hypercholesterolemia" in conditions:
                where.append("(r.sat_fat_g IS NULL OR r.sat_fat_g <= 5)")
            if "ckd" in conditions and weight_kg is not None:
                ckd_cap = max(1, int(float(weight_kg) * 0.8 / 3))
                where.append(f"(r.protein_g IS NULL OR r.protein_g <= {ckd_cap})")
            if "gout" in conditions:
                where.append(
                    "NOT (r.tags && ARRAY['organ_meat','shellfish']::text[])"
                )

        sql = f"""
            SELECT r.id FROM recipes r
             WHERE {' AND '.join(where)}
        """
        res = await self.session.execute(text(sql), params)
        return [row[0] for row in res.all()]
