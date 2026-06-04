"""Closed vocabularies — single runtime source of truth.

Mirrors the DDL enums defined in migration 0001 (allergen_enum, condition_enum,
goal_enum, activity_level_enum, meal_time_enum). Used by catalog ingest
validators, ConditionGate registry, property tests, and any code that needs
to assert a value is a member of a closed set.

Per ADR-0001 these vocabularies are frozen — extension requires an ADR + an
Alembic migration that ALTERs the enum + a follow-up catalog rebuild.
"""

from __future__ import annotations

from typing import Final

# 14 declared allergens (FALCPA + EU 1169 union).
ALLERGENS_14: Final[frozenset[str]] = frozenset(
    {
        "dairy",
        "gluten",
        "tree_nuts",
        "peanuts",
        "shellfish",
        "fish",
        "egg",
        "soy",
        "sesame",
        "celery",
        "mustard",
        "lupin",
        "sulphites",
        "molluscs",
    }
)

# 25 medical conditions covered by the platform.
CONDITIONS_25: Final[frozenset[str]] = frozenset(
    {
        "diabetes_t1",
        "diabetes_t2",
        "hypertension",
        "dyslipidemia",
        "hypercholesterolemia",
        "hypothyroidism",
        "hyperthyroidism",
        "ibs",
        "ibd",
        "celiac",
        "lactose_intolerance",
        "obesity",
        "overweight",
        "pregnancy",
        "lactation",
        "athletic_load",
        "ckd",
        "ischemic_heart_disease",
        "fatty_liver",
        "iron_deficiency_anemia",
        "pcos",
        "gout",
        "vitamin_d_deficiency",
        "chronic_insomnia",
        "mild_depression",
    }
)

GOALS_5: Final[frozenset[str]] = frozenset(
    {
        "weight_loss",
        "maintain",
        "muscle_gain",
        "weight_gain",
        "health",
    }
)

MEAL_TIMES_4: Final[frozenset[str]] = frozenset(
    {
        "breakfast",
        "lunch",
        "dinner",
        "snack",
    }
)

ACTIVITY_LEVELS_5: Final[frozenset[str]] = frozenset(
    {
        "sedentary",
        "lightly_active",
        "moderately_active",
        "very_active",
        "extra_active",
    }
)

LOCALES_5: Final[frozenset[str]] = frozenset({"en", "es", "pt", "fr", "de"})

REGIONS_5: Final[frozenset[str]] = frozenset({"us", "ca", "eu", "uk", "latam"})
