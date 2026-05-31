"""Tracking domain — water + weight only for Sprint 3.

Food logs land in Sprint 5 (Vision IA). Fasting/grocery in Sprint 7.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID


@dataclass(slots=True)
class WaterLog:
    user_id: UUID
    time: datetime
    ml: int
    target_ml: int | None = None


@dataclass(slots=True)
class WeightLog:
    user_id: UUID
    time: datetime
    weight_kg: Decimal
    body_fat_pct: Decimal | None = None
    waist_cm: Decimal | None = None
    photo_url: str | None = None
