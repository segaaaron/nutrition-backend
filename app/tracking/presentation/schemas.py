"""Pydantic schemas for tracking endpoints."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class LogWaterRequest(_Strict):
    ml: int = Field(ge=1, le=5000)


class LogWaterResponse(_Strict):
    total_today_ml: int
    goal_ml: int | None = None  # populated by GET /logs/water/today; omitted on POST


class LogWeightRequest(_Strict):
    weight_kg: Decimal = Field(ge=Decimal("20"), le=Decimal("300"))
    body_fat_pct: Decimal | None = Field(default=None, ge=Decimal("3"), le=Decimal("60"))
    waist_cm: Decimal | None = Field(default=None, ge=Decimal("30"), le=Decimal("200"))
    photo_url: str | None = None


class TrendPoint(_Strict):
    t: datetime
    value: float


class WeightTrendResponse(_Strict):
    window_days: int
    points: list[TrendPoint]
