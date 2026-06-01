"""Profile Pydantic schemas. Strict.

Mobile contract: see `docs/mobile/ONBOARDING_API_CONTRACT.md` for the iOS +
Android client-facing field map, conditional fields, and error-handling table.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# Sex semantics: internal rename per ADR-0012 (planned) is `sex_at_birth`. UI
# label stays "Sexo" / "Sex"; field name stays `sex` for v1 wire compat.
Sex = Literal["male", "female"]
Units = Literal["metric", "imperial"]
Goal = Literal["weight_loss", "maintain", "muscle_gain", "weight_gain", "health"]
ActivityLevel = Literal[
    "sedentary", "lightly_active", "moderately_active", "very_active", "extra_active"
]
Theme = Literal["light", "dark"]
Locale = Literal["en", "es", "pt", "fr", "de"]
DietaryPattern = Literal["omnivore", "pescatarian", "vegetarian", "vegan"]
Trimester = Literal["first", "second", "third"]


# Closed condition + allergen subsets the mobile UI uses (chips). The wider
# vocabularies live in `app/shared/domain/vocabularies.py`; this short list is
# what the iOS / Android chips actually render.
MobileCondition = Literal[
    "diabetes_t2", "hypertension", "celiac",
    "dyslipidemia",  # mapped from UI chip "Colesterol alto"
    "hypothyroidism",
    "lactation",     # H2.1 lifted (ADR-0016)
    "pregnancy",     # H2.2 — mobile may send even though server still gates
]
MobileAllergen = Literal[
    "dairy", "gluten", "tree_nuts", "shellfish", "egg", "soy",
]


class OnboardingRequest(_Strict):
    """Single onboarding payload submitted by iOS / Android clients.

    Required minimum: age, sex, weight_kg, height_cm OR height_m, goal,
    activity_level, dietary_pattern. Everything else optional with explicit
    server-side fallback rules.
    """

    # Identity
    name: str | None = Field(
        default=None, max_length=120,
        json_schema_extra={"example": "Miguel Saravia"},
    )

    # Biometrics
    age: int = Field(
        ge=18, le=80,
        json_schema_extra={"example": 30, "description": "Adult onboarding only. Pediatric (<18) + geriatric (>80) refused."},
    )
    sex: Sex = Field(
        json_schema_extra={"example": "male", "description": "Sex at birth — drives Mifflin BMR formula."},
    )
    units: Units = Field(
        default="metric",
        json_schema_extra={"description": "Display preference only. Server stores SI."},
    )
    weight_kg: Decimal = Field(
        ge=Decimal("30"), le=Decimal("250"),
        json_schema_extra={"example": "72.0"},
    )
    # Either send height_cm OR height_m; if both, height_cm wins.
    height_cm: Decimal | None = Field(
        default=None, ge=Decimal("120"), le=Decimal("240"),
        json_schema_extra={"example": "175.0"},
    )
    height_m: Decimal | None = Field(
        default=None, ge=Decimal("1.20"), le=Decimal("2.40"),
        json_schema_extra={"example": "1.75", "description": "Meters input (iOS form). Server converts to cm."},
    )
    bodyfat_pct: Decimal | None = Field(
        default=None, ge=Decimal("3"), le=Decimal("60"),
        json_schema_extra={"example": "18.5", "description": "Optional. Enables Cunningham BMR for athletes."},
    )

    # Goals
    goal: Goal = Field(json_schema_extra={"example": "weight_loss"})
    activity_level: ActivityLevel = Field(json_schema_extra={"example": "moderately_active"})
    dietary_pattern: DietaryPattern = Field(
        json_schema_extra={"example": "omnivore", "description": "Mandatory. Catalog filter; without it vegans risk meat exposure."},
    )

    # Conditions
    medical_conditions: list[MobileCondition] = Field(
        default_factory=list, max_length=6,
        json_schema_extra={"description": 'Closed enum. UI chip "Colesterol alto" → "dyslipidemia". UI chip "Celiaquía" → write BOTH "celiac" here AND "gluten" in allergies.'},
    )
    other_condition: str | None = Field(
        default=None, max_length=200,
        json_schema_extra={"description": 'UI "Otros…" free text. Stored as PII; NOT routed to Layer1 clinical filter. Warning surfaced to user.'},
    )

    # Allergens
    allergies: list[MobileAllergen] = Field(
        default_factory=list, max_length=7,
        json_schema_extra={"description": 'Closed enum. Filter applied at Layer1.'},
    )
    other_allergy: str | None = Field(
        default=None, max_length=200,
        json_schema_extra={"description": 'UI "Otra alergia…" free text. NON-EMPTY value REFUSES plan generation — server returns 422 problem `urn:nova:problem:plan:allergen-unmapped-requires-review`.'},
    )

    # Pregnancy / lactation conditional fields
    trimester: Trimester | None = Field(
        default=None,
        json_schema_extra={"description": 'Required iff "pregnancy" in medical_conditions. iOS / Android show only when pregnancy chip selected.'},
    )
    is_exclusively_breastfeeding: bool | None = Field(
        default=None,
        json_schema_extra={"description": 'Required iff "lactation" in medical_conditions. true → +500 kcal/day; false → +250 kcal/day partial.'},
    )

    # Region / locale
    country: str | None = Field(
        default=None, min_length=2, max_length=2,
        json_schema_extra={"example": "PE", "description": "ISO 3166-1 alpha-2."},
    )
    locale: Locale | None = Field(
        default=None,
        json_schema_extra={"description": "Optional. Server falls back to Accept-Language header → region default."},
    )
    theme: Theme = "light"

    @model_validator(mode="after")
    def _validate(self) -> "OnboardingRequest":
        # Refuse on unmapped allergen free text — safety hard-stop.
        if self.other_allergy and self.other_allergy.strip():
            raise ValueError("allergen_unmapped_requires_review")
        # Exactly one of height_cm / height_m must be supplied.
        if self.height_cm is None and self.height_m is None:
            raise ValueError("height_required")
        # Conditional fields: pregnancy requires trimester; lactation requires bf flag.
        if "pregnancy" in self.medical_conditions and self.trimester is None:
            raise ValueError("trimester_required_for_pregnancy")
        if "lactation" in self.medical_conditions and self.is_exclusively_breastfeeding is None:
            raise ValueError("breastfeeding_status_required_for_lactation")
        return self

    @property
    def resolved_height_cm(self) -> Decimal:
        if self.height_cm is not None:
            return self.height_cm
        assert self.height_m is not None
        return (self.height_m * Decimal("100")).quantize(Decimal("0.1"))


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
