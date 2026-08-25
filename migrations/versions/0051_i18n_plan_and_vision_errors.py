"""0051 — i18n seeds: BE-11 portion errors, plan errors, B7 vision confirm errors.

Seeds Spanish + English translations for error codes that were missing from
the i18n_translations table:

  BE-11: user_factor_out_of_range, user_factor_not_quarter, meal_already_completed,
         swap_pool_exhausted_for_slot
  B7:    vision_job_not_completed, vision_job_already_confirmed
  Plan:  onboarding_incomplete, nutritional_goals_missing, nutritional_goals_unavailable,
         no_candidates_for_meal, plan_generation_yielded_no_meals, height_required,
         allergen_unmapped_requires_review, trimester_required_for_pregnancy,
         breastfeeding_status_required_for_lactation, segment_unsupported_mvp,
         profile_missing, grocery_generation_yielded_no_items, region_audit_unavailable
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0051_i18n_plan_and_vision_errors"
down_revision = "0050_plan_meals_user_factor"
branch_labels = None
depends_on = None

_I18N_ERRORS: dict[str, dict[str, dict[str, str]]] = {
    # ── BE-11 portion adjustment ──────────────────────────────────────────────
    "user_factor_out_of_range": {
        "user_factor_out_of_range.title": {
            "es": "Factor de porción fuera de rango",
            "en": "Portion factor out of range",
        },
        "user_factor_out_of_range.detail": {
            "es": "El factor de porción debe estar entre 0.25 y 2.0.",
            "en": "Portion factor must be between 0.25 and 2.0.",
        },
    },
    "user_factor_not_quarter": {
        "user_factor_not_quarter.title": {
            "es": "Factor de porción inválido",
            "en": "Invalid portion factor",
        },
        "user_factor_not_quarter.detail": {
            "es": "El factor de porción debe ser múltiplo de 0.25 (ej: 0.25, 0.50, 0.75, 1.0...).",
            "en": "Portion factor must be a multiple of 0.25 (e.g. 0.25, 0.50, 0.75, 1.0...).",
        },
    },
    "meal_already_completed": {
        "meal_already_completed.title": {
            "es": "Comida ya completada",
            "en": "Meal already completed",
        },
        "meal_already_completed.detail": {
            "es": "Esta comida ya fue completada y no se puede ajustar la porción.",
            "en": "This meal is already completed — portion cannot be adjusted.",
        },
    },
    "swap_pool_exhausted_for_slot": {
        "swap_pool_exhausted_for_slot.title": {
            "es": "Sin alternativas disponibles",
            "en": "No alternatives available",
        },
        "swap_pool_exhausted_for_slot.detail": {
            "es": "No hay recetas disponibles para cambiar esta comida con tus restricciones.",
            "en": "No alternative recipes available for this meal slot with your restrictions.",
        },
    },
    # ── B7 vision confirm ─────────────────────────────────────────────────────
    "vision_job_not_completed": {
        "vision_job_not_completed.title": {
            "es": "Análisis de foto no completado",
            "en": "Photo analysis not yet complete",
        },
        "vision_job_not_completed.detail": {
            "es": "El análisis de la foto aún no terminó. Espera unos segundos e intenta de nuevo.",
            "en": "Photo analysis has not finished yet. Wait a moment and try again.",
        },
    },
    "vision_job_already_confirmed": {
        "vision_job_already_confirmed.title": {
            "es": "Foto ya registrada",
            "en": "Photo already logged",
        },
        "vision_job_already_confirmed.detail": {
            "es": "Esta foto ya fue guardada en tu registro de alimentos.",
            "en": "This photo has already been saved to your food log.",
        },
    },
    # ── Plan generation errors ────────────────────────────────────────────────
    "onboarding_incomplete": {
        "onboarding_incomplete.title": {
            "es": "Perfil incompleto",
            "en": "Onboarding incomplete",
        },
        "onboarding_incomplete.detail": {
            "es": "Completa tu perfil antes de generar un plan nutricional.",
            "en": "Complete your profile before generating a nutrition plan.",
        },
    },
    "nutritional_goals_missing": {
        "nutritional_goals_missing.title": {
            "es": "Metas nutricionales no encontradas",
            "en": "Nutritional goals missing",
        },
        "nutritional_goals_missing.detail": {
            "es": "Completa el onboarding para que calculemos tus metas nutricionales.",
            "en": "Complete onboarding first so we can calculate your nutritional goals.",
        },
    },
    "nutritional_goals_unavailable": {
        "nutritional_goals_unavailable.title": {
            "es": "Perfil incompleto",
            "en": "Profile incomplete",
        },
        "nutritional_goals_unavailable.detail": {
            "es": "Necesitamos más información de tu perfil para generar el plan.",
            "en": "We need more profile information to generate your plan.",
        },
    },
    "no_candidates_for_meal": {
        "no_candidates_for_meal.title": {
            "es": "Sin recetas disponibles",
            "en": "No recipes available",
        },
        "no_candidates_for_meal.detail": {
            "es": "No encontramos recetas que coincidan con tus restricciones para este tiempo de comida.",
            "en": "No recipes match your restrictions for this meal slot.",
        },
    },
    "plan_generation_yielded_no_meals": {
        "plan_generation_yielded_no_meals.title": {
            "es": "No se pudo generar el plan",
            "en": "Plan generation failed",
        },
        "plan_generation_yielded_no_meals.detail": {
            "es": "No hay suficientes recetas disponibles con tus restricciones actuales.",
            "en": "Not enough recipes are available for your current restrictions.",
        },
    },
    "height_required": {
        "height_required.title": {
            "es": "Estatura requerida",
            "en": "Height required",
        },
        "height_required.detail": {
            "es": "Necesitamos tu estatura para calcular tu plan nutricional.",
            "en": "We need your height to calculate your nutrition plan.",
        },
    },
    "allergen_unmapped_requires_review": {
        "allergen_unmapped_requires_review.title": {
            "es": "Alérgeno sin clasificar",
            "en": "Allergen unclassified",
        },
        "allergen_unmapped_requires_review.detail": {
            "es": "Uno de tus alérgenos no está en nuestra lista. Contacta a soporte.",
            "en": "One of your allergens is not in our list. Please contact support.",
        },
    },
    "trimester_required_for_pregnancy": {
        "trimester_required_for_pregnancy.title": {
            "es": "Trimestre requerido",
            "en": "Trimester required",
        },
        "trimester_required_for_pregnancy.detail": {
            "es": "Indica en qué trimestre del embarazo estás para ajustar tu plan.",
            "en": "Please indicate which trimester of pregnancy you are in to tailor your plan.",
        },
    },
    "breastfeeding_status_required_for_lactation": {
        "breastfeeding_status_required_for_lactation.title": {
            "es": "Estado de lactancia requerido",
            "en": "Breastfeeding status required",
        },
        "breastfeeding_status_required_for_lactation.detail": {
            "es": "Indica si estás en lactancia exclusiva para ajustar tu plan nutricional.",
            "en": "Please indicate whether you are exclusively breastfeeding to tailor your plan.",
        },
    },
    "segment_unsupported_mvp": {
        "segment_unsupported_mvp.title": {
            "es": "No disponible aún",
            "en": "Not available yet",
        },
        "segment_unsupported_mvp.detail": {
            "es": "Este tipo de usuario no está disponible en la versión actual de la app.",
            "en": "This user type is not available in the current version of the app.",
        },
    },
    "profile_missing": {
        "profile_missing.title": {
            "es": "Campo de perfil requerido",
            "en": "Required profile field missing",
        },
        "profile_missing.detail": {
            "es": "Falta información en tu perfil necesaria para generar el plan.",
            "en": "Your profile is missing information required to generate the plan.",
        },
    },
    "grocery_generation_yielded_no_items": {
        "grocery_generation_yielded_no_items.title": {
            "es": "Lista de compras vacía",
            "en": "Grocery list empty",
        },
        "grocery_generation_yielded_no_items.detail": {
            "es": "No se pudieron generar elementos para tu lista de compras.",
            "en": "Could not generate items for your grocery list.",
        },
    },
    "region_audit_unavailable": {
        "region_audit_unavailable.title": {
            "es": "Cambio de región no disponible",
            "en": "Region change unavailable",
        },
        "region_audit_unavailable.detail": {
            "es": "No se pudo registrar el cambio de región. Intenta de nuevo.",
            "en": "Could not record the region change. Please try again.",
        },
    },
}


def upgrade() -> None:
    conn = op.get_bind()
    for _group_key, entries in _I18N_ERRORS.items():
        for key, by_locale in entries.items():
            for locale, value in by_locale.items():
                conn.execute(
                    sa.text(
                        "INSERT INTO i18n_translations(scope, key, locale, value) "
                        "VALUES ('error', :k, :l, :v) "
                        "ON CONFLICT (scope, key, locale) DO UPDATE SET value = EXCLUDED.value"
                    ),
                    {"k": key, "l": locale, "v": value},
                )


def downgrade() -> None:
    conn = op.get_bind()
    for _group_key, entries in _I18N_ERRORS.items():
        for key, by_locale in entries.items():
            for locale in by_locale:
                conn.execute(
                    sa.text(
                        "DELETE FROM i18n_translations "
                        "WHERE scope = 'error' AND key = :k AND locale = :l"
                    ),
                    {"k": key, "l": locale},
                )
