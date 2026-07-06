"""Ischemic heart disease condition gate — ConditionGate Strategy.

Restricts saturated fat + sodium per AHA/ACC 2019 Primary Prevention
guideline and ACC/AHA 2017 BP guideline — same thresholds as
hypercholesterolemia + hypertension combined, since atherosclerotic disease
demands both lipid and pressure management.

Sources:
  - Arnett DK et al., 2019 ACC/AHA Guideline on the Primary Prevention of
    Cardiovascular Disease, Circulation 2019;140:e596-e646.
  - Whelton PK et al., 2017 ACC/AHA HBP Guideline, Hypertension 2018;71:e13.

NOVA scope: nutrition planning only.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IschemicHeartDiseaseGate:
    condition: str = "ischemic_heart_disease"

    def contribute_sql(self) -> tuple[str, dict[str, object]]:
        sql = (
            "(r.sat_fat_g IS NOT NULL AND r.sat_fat_g <= :ihd_satfat_max"
            " AND r.sodium_mg IS NOT NULL AND r.sodium_mg <= :ihd_sodium_max)"
        )
        params: dict[str, object] = {
            "ihd_satfat_max": 5,
            "ihd_sodium_max": 600,
        }
        return sql, params
