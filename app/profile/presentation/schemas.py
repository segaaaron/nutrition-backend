"""Profile Pydantic schemas. Strict.

Mobile contract: see `docs/mobile/IOS_API_REFERENCE.md` §3 for the iOS +
Android client-facing field map, conditional fields, and error-handling table.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.logging import get_logger

_log = get_logger("profile.schemas")


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
Locale = Literal["en", "es"]
DietaryPattern = Literal["omnivore", "pescatarian", "vegetarian", "vegan"]
Trimester = Literal["first", "second", "third"]


# Closed condition + allergen subsets the mobile UI uses (chips). The wider
# vocabularies live in `app/shared/domain/vocabularies.py`; this short list is
# what the iOS / Android chips actually render.
# 2026-07-09: onboarding scope reduced to general nutrition (owner decision).
# NOVA is a general LATAM nutrition app, NOT a clinical tool (project REGLA #1).
# Accepted = one nutrition-managed situation (fatty_liver) + two life stages
# (pregnancy, lactation). Medical conditions (diabetes_t2, hypertension,
# dyslipidemia, hypothyroidism) are NO LONGER accepted — they need medical care
# out of scope. Celiac / lactose intolerance are handled via ALLERGENS
# (gluten / dairy), not as conditions. The DB `condition_enum` keeps all its
# values (no migration); this API boundary is the enforcement point, and the
# dormant medical condition gates simply never fire.
MobileCondition = Literal[
    "fatty_liver",  # NAFLD/NASH — nutrition-managed (Mediterranean, low sugar/sat-fat)
    "pregnancy",  # life stage — kcal surplus by trimester (+ trimester selector)
    "lactation",  # life stage — kcal surplus (+ breastfeeding section)
]
MobileAllergen = Literal[
    "dairy",
    "gluten",
    "tree_nuts",
    "shellfish",
    "egg",
    "soy",
]


class OnboardingRequest(_Strict):
    """Single onboarding payload submitted by iOS / Android clients.

    Required minimum: age, sex, weight_kg, height_cm OR height_m, goal,
    activity_level, dietary_pattern. Everything else optional with explicit
    server-side fallback rules.
    """

    # Identity
    name: str | None = Field(
        default=None,
        max_length=120,
        json_schema_extra={"example": "Miguel Saravia"},
    )

    # Biometrics
    age: int = Field(
        ge=18,
        le=80,
        json_schema_extra={
            "example": 30,
            "description": "Adult onboarding only. Pediatric (<18) + geriatric (>80) refused.",
        },
    )
    sex: Sex = Field(
        json_schema_extra={
            "example": "male",
            "description": "Sex at birth — drives Mifflin BMR formula.",
        },
    )
    weight_kg: Decimal = Field(
        ge=Decimal("30"),
        le=Decimal("250"),
        json_schema_extra={"example": "72.0"},
    )
    # Either send height_cm OR height_m; if both, height_cm wins.
    height_cm: Decimal | None = Field(
        default=None,
        ge=Decimal("120"),
        le=Decimal("240"),
        json_schema_extra={"example": "175.0"},
    )
    height_m: Decimal | None = Field(
        default=None,
        ge=Decimal("1.20"),
        le=Decimal("2.40"),
        json_schema_extra={
            "example": "1.75",
            "description": "Meters input (iOS form). Server converts to cm.",
        },
    )
    bodyfat_pct: Decimal | None = Field(
        default=None,
        ge=Decimal("3"),
        le=Decimal("60"),
        json_schema_extra={
            "example": "18.5",
            "description": "Optional. Enables Cunningham BMR for athletes.",
        },
    )

    # Goals
    goal: Goal = Field(json_schema_extra={"example": "weight_loss"})
    activity_level: ActivityLevel = Field(json_schema_extra={"example": "moderately_active"})
    dietary_pattern: DietaryPattern | None = Field(
        default=None,
        json_schema_extra={
            "example": "omnivore",
            "description": (
                "Optional. iOS MVP onboarding does NOT ask this field; backend "
                "defaults to 'omnivore' when omitted and emits a structured "
                "warning log ('dietary_pattern_defaulted_to_omnivore'). "
                "RISK: vegan users who silently default to omnivore will receive "
                "meat-containing recipes until they call PATCH /me. iOS clients "
                "SHOULD add a dietary-pattern screen post-MVP. Per decision D1 "
                "(ADR-0028)."
            ),
        },
    )

    # Conditions
    medical_conditions: list[MobileCondition] = Field(
        default_factory=list,
        max_length=6,
        json_schema_extra={
            "description": 'Closed enum (general nutrition only): "fatty_liver", "pregnancy", "lactation". Celiac → send "gluten" in allergies; lactose intolerance → send "dairy" in allergies. Medical conditions (diabetes, hypertension, etc.) are out of scope.'
        },
    )
    other_condition: str | None = Field(
        default=None,
        max_length=200,
        json_schema_extra={
            "deprecated": True,
            "description": (
                "DEPRECATED (iOS 2026-06+ form removes this field). Free text "
                "override stored as PII; NOT routed to Layer1 condition filter. "
                "Legacy clients tolerated: value is persisted if sent but ignored "
                "by filters. NEW clients MUST NOT send this field."
            )
        },
    )

    # Allergens
    allergies: list[MobileAllergen] = Field(
        default_factory=list,
        max_length=7,
        json_schema_extra={"description": "Closed enum. Filter applied at Layer1."},
    )
    other_allergy: str | None = Field(
        default=None,
        max_length=200,
        json_schema_extra={
            "deprecated": True,
            "description": (
                "DEPRECATED (iOS 2026-06+ form removes this field). Previously: "
                "non-empty value refused plan generation. Now: legacy clients "
                "tolerated — value is logged as a warning and silently ignored "
                "(no plan refuse). NEW clients MUST NOT send this field."
            )
        },
    )

    # Pregnancy / lactation conditional fields
    trimester: Trimester | None = Field(
        default=None,
        json_schema_extra={
            "description": 'Required iff "pregnancy" in medical_conditions. iOS / Android show only when pregnancy chip selected.'
        },
    )
    is_exclusively_breastfeeding: bool | None = Field(
        default=None,
        json_schema_extra={
            "description": 'Required iff "lactation" in medical_conditions. true → +500 kcal/day; false → +250 kcal/day partial.'
        },
    )

    # Region / locale
    country: str | None = Field(
        default=None,
        min_length=2,
        max_length=2,
        json_schema_extra={"example": "PE", "description": "ISO 3166-1 alpha-2."},
    )
    locale: Locale | None = Field(
        default=None,
        json_schema_extra={
            "description": "Optional. Server falls back to Accept-Language header → region default."
        },
    )

    @model_validator(mode="after")
    def _validate(self) -> OnboardingRequest:
        # Legacy clients may still send `other_allergy`. iOS 2026-06+ form
        # removes the field, so production traffic should be zero. Tolerate
        # legacy payloads: warn + ignore, do NOT refuse the plan. The
        # previous 422 hard-stop produced an unrecoverable dead-end UI for
        # any client that hadn't been updated yet.
        if self.other_allergy and self.other_allergy.strip():
            _log.warning(
                "onboarding.other_allergy_ignored",
                text_length=len(self.other_allergy),
            )
            self.other_allergy = None
        if self.other_condition and self.other_condition.strip():
            # Persist as PII (no filter routing). Track the legacy field so
            # we can confirm production iOS no longer sends it.
            _log.info(
                "onboarding.other_condition_received_legacy",
                text_length=len(self.other_condition),
            )
        # Exactly one of height_cm / height_m must be supplied.
        if self.height_cm is None and self.height_m is None:
            raise ValueError("height_required")
        # Lactation: default exclusive=True if not specified (IOM DRI 2002 safer baseline).
        # Mobile chip-based onboarding does NOT collect the breastfeeding flag,
        # so the server back-fills with the higher-energy exclusive value
        # (+500 kcal/day) to avoid under-feeding lactating mothers. Clients can
        # later PATCH the field once a parcial vs exclusiva distinction is in
        # the UI.
        if (
            "lactation" in self.medical_conditions
            and self.is_exclusively_breastfeeding is None
        ):
            _log.info(
                "onboarding.lactation_breastfeeding_defaulted_exclusive",
                source="IOM_DRI_2002",
            )
            self.is_exclusively_breastfeeding = True
        # Pregnancy: default third trimester if not specified (highest demand).
        # Same rationale as lactation — chip-based UI omits the trimester
        # selector. Third trimester (+452 kcal/day, IOM DRI 2002) is the
        # safest default; under-feeding T3 carries greater risk than mildly
        # over-feeding T1.
        if "pregnancy" in self.medical_conditions and self.trimester is None:
            _log.info(
                "onboarding.pregnancy_trimester_defaulted_third",
                source="IOM_DRI_2002",
            )
            self.trimester = "third"
        return self

    @property
    def resolved_height_cm(self) -> Decimal:
        if self.height_cm is not None:
            return self.height_cm
        assert self.height_m is not None
        return (self.height_m * Decimal("100")).quantize(Decimal("0.1"))


class ProfilePatch(_Strict):
    name: str | None = Field(default=None, max_length=120)
    age: int | None = Field(default=None, ge=18, le=80)
    sex: Sex | None = None
    weight_kg: Decimal | None = Field(default=None, gt=Decimal("20"), lt=Decimal("300"))
    height_cm: Decimal | None = Field(default=None, gt=Decimal("50"), lt=Decimal("250"))
    goal_weight_kg: Decimal | None = Field(default=None, gt=Decimal("20"), lt=Decimal("300"))
    goal: Goal | None = None
    activity_level: ActivityLevel | None = None
    medical_conditions: list[MobileCondition] | None = Field(default=None, max_length=6)
    other_condition: str | None = Field(default=None, max_length=200)
    allergies: list[MobileAllergen] | None = Field(default=None, max_length=7)
    other_allergy: str | None = Field(default=None, max_length=200)
    country: str | None = Field(default=None, min_length=2, max_length=2)


class LocalePatch(_Strict):
    locale: Locale


class PlanJobInfo(_Strict):
    """Async plan generation job kicked off automatically by `POST /me/onboarding`.

    Mobile clients poll `GET /plans/active` (or use the job_id with the
    plan status endpoint) until the plan is ready. `status` mirrors the
    Arq job lifecycle at enqueue time — always "queued" on the first
    response. When the broker is unavailable the field is omitted from
    the response and the client must fall back to `POST /plans` itself.
    """

    job_id: str
    status: Literal["queued"]


class ProfileResponse(_Strict):
    user_id: UUID
    name: str | None
    age: int | None
    sex: Sex | None
    units: Units
    weight_kg: float | None
    height_cm: float | None
    goal_weight_kg: float | None = None
    starting_weight_kg: float | None = None
    # Pre-converted display values — iOS reads these directly, no client math needed.
    # Imperial: weight_display = lbs (1 decimal), height_ft + height_in (integers).
    # Metric: weight_display = kg (1 decimal), height_ft/height_in = None.
    weight_display: float | None = None
    weight_unit: str | None = None
    height_display_primary: int | None = None
    height_display_secondary: int | None = None
    height_unit: str | None = None
    goal: Goal | None
    activity_level: ActivityLevel | None
    dietary_pattern: DietaryPattern | None = None
    # BE-2 (2026-07-10): returned so iOS can prefill the plan form on
    # re-create without the user re-entering saved data. null when not set.
    bodyfat_pct: float | None = None
    trimester: Trimester | None = None
    is_exclusively_breastfeeding: bool | None = None
    medical_conditions: list[str]
    other_condition: str | None
    allergies: list[str]
    other_allergy: str | None
    country: str | None
    region: str | None
    locale: str
    onboarding_completed: bool
    updated_at: datetime | None
    plan_job: PlanJobInfo | None = None


class LocaleResponse(_Strict):
    locale: str
