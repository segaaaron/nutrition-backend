"""Plan value objects + enums."""

from __future__ import annotations

from typing import Literal

PlanType = Literal["day", "week", "month"]
PlanStatus = Literal["active", "completed", "cancelled"]
MealTime = Literal["breakfast", "lunch", "dinner", "snack", "morning_snack", "afternoon_snack"]
Difficulty = Literal["easy", "medium", "hard"]

# Spec §6 preferences (closed vocabulary).
Preference = Literal[
    "keto",
    "vegetarian",
    "vegan",
    "high_protein",
    "low_sodium",
    "mediterranean",
    "low_carb",
]

PLAN_TYPE_TO_DAYS: dict[PlanType, int] = {"day": 1, "week": 7, "month": 30}
