"""Profile entities."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

Sex = Literal["male", "female"]
Units = Literal["metric", "imperial"]
Goal = Literal["weight_loss", "maintain", "muscle_gain", "weight_gain", "health"]
ActivityLevel = Literal[
    "sedentary", "lightly_active", "moderately_active", "very_active", "extra_active"
]
Theme = Literal["light", "dark"]


@dataclass(slots=True)
class UserProfile:
    user_id: UUID
    name: str | None = None
    age: int | None = None
    sex: Sex | None = None
    units: Units = "metric"
    weight_kg: Decimal | None = None
    height_cm: Decimal | None = None
    goal: Goal | None = None
    activity_level: ActivityLevel | None = None
    medical_conditions: list[str] = field(default_factory=list)
    other_condition: str | None = None
    allergies: list[str] = field(default_factory=list)
    other_allergy: str | None = None
    country: str | None = None
    region: str | None = None
    locale: str = "en"
    theme: Theme = "light"
    onboarding_completed: bool = False
    updated_at: datetime | None = None

    @property
    def is_complete_enough_for_targets(self) -> bool:
        return (
            self.age is not None
            and self.sex is not None
            and self.weight_kg is not None
            and self.height_cm is not None
            and self.goal is not None
            and self.activity_level is not None
        )
