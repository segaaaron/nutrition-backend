"""Profile Pydantic schemas. Strict."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


Sex = Literal["male", "female"]
Units = Literal["metric", "imperial"]
Goal = Literal["weight_loss", "maintain", "muscle_gain", "weight_gain", "health"]
ActivityLevel = Literal[
    "sedentary", "lightly_active", "moderately_active", "very_active", "extra_active"
]
Theme = Literal["light", "dark"]
Locale = Literal["en", "es", "pt", "fr", "de"]


class OnboardingRequest(_Strict):
    name: str | None = Field(default=None, max_length=120)
    age: int = Field(ge=12, le=100, json_schema_extra={"example": 30})
    sex: Sex
    units: Units = "metric"
    weight_kg: Decimal = Field(gt=Decimal("20"), lt=Decimal("300"), json_schema_extra={"example": "70.0"})
    height_cm: Decimal = Field(gt=Decimal("50"), lt=Decimal("250"), json_schema_extra={"example": "175.0"})
    goal: Goal
    activity_level: ActivityLevel
    medical_conditions: list[str] = Field(default_factory=list)
    allergies: list[str] = Field(default_factory=list)
    country: str | None = Field(default=None, min_length=2, max_length=2, json_schema_extra={"example": "PE"})
    locale: Locale | None = None
    theme: Theme = "light"


class ProfilePatch(_Strict):
    name: str | None = None
    age: int | None = Field(default=None, ge=12, le=100)
    sex: Sex | None = None
    units: Units | None = None
    weight_kg: Decimal | None = Field(default=None, gt=Decimal("20"), lt=Decimal("300"))
    height_cm: Decimal | None = Field(default=None, gt=Decimal("50"), lt=Decimal("250"))
    goal: Goal | None = None
    activity_level: ActivityLevel | None = None
    medical_conditions: list[str] | None = None
    other_condition: str | None = None
    allergies: list[str] | None = None
    other_allergy: str | None = None
    country: str | None = Field(default=None, min_length=2, max_length=2)
    theme: Theme | None = None


class LocalePatch(_Strict):
    locale: Locale


class ProfileResponse(_Strict):
    user_id: UUID
    name: str | None
    age: int | None
    sex: Sex | None
    units: Units
    weight_kg: Decimal | None
    height_cm: Decimal | None
    goal: Goal | None
    activity_level: ActivityLevel | None
    medical_conditions: list[str]
    other_condition: str | None
    allergies: list[str]
    other_allergy: str | None
    country: str | None
    region: str | None
    locale: str
    theme: Theme
    onboarding_completed: bool
    updated_at: datetime | None


class LocaleResponse(_Strict):
    locale: str
