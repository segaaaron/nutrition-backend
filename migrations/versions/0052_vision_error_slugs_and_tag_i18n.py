"""0052 — i18n seeds: C14 vision error slugs + C6-b recipe tag slugs.

C14 — maps stable vision error slugs so iOS can display localized messages:
  vision_cost_cap, vision_provider_unavailable, vision_timeout,
  vision_image_unreadable, vision_internal.

C6-b — closed catalog of recipe tag slugs for PlanMealResponse.tags_localized:
  objective_*, meal_time_*, diet_*, prep_*.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0052_vision_error_slugs_and_tag_i18n"
down_revision = "0051_i18n_plan_and_vision_errors"
branch_labels = None
depends_on = None

_VISION_ERRORS: dict[str, dict[str, str]] = {
    "vision_cost_cap": {
        "es": "Límite de análisis alcanzado. Intenta más tarde.",
        "en": "Analysis limit reached. Please try again later.",
    },
    "vision_provider_unavailable": {
        "es": "El servicio de análisis no está disponible. Intenta más tarde.",
        "en": "Analysis service is unavailable. Please try again later.",
    },
    "vision_timeout": {
        "es": "El análisis tardó demasiado. Intenta de nuevo.",
        "en": "Analysis timed out. Please try again.",
    },
    "vision_image_unreadable": {
        "es": "No pudimos leer la imagen. Toma otra foto con mejor iluminación.",
        "en": "Could not read the image. Try a photo with better lighting.",
    },
    "vision_internal": {
        "es": "Error interno al analizar la foto. Intenta de nuevo.",
        "en": "Internal error while analysing the photo. Please try again.",
    },
}

_TAGS: dict[str, dict[str, str]] = {
    # Objectives
    "weight_loss": {"es": "Pérdida de peso", "en": "Weight loss"},
    "muscle_gain": {"es": "Ganancia muscular", "en": "Muscle gain"},
    "maintenance": {"es": "Mantenimiento", "en": "Maintenance"},
    # Diet style
    "high_protein": {"es": "Alto en proteína", "en": "High protein"},
    "low_fat": {"es": "Bajo en grasa", "en": "Low fat"},
    "low_carb": {"es": "Bajo en carbohidratos", "en": "Low carb"},
    "high_fiber": {"es": "Alto en fibra", "en": "High fiber"},
    "low_sodium": {"es": "Bajo en sodio", "en": "Low sodium"},
    "low_sugar": {"es": "Bajo en azúcar", "en": "Low sugar"},
    "vegetarian": {"es": "Vegetariano", "en": "Vegetarian"},
    "vegan": {"es": "Vegano", "en": "Vegan"},
    "gluten_free": {"es": "Sin gluten", "en": "Gluten free"},
    "dairy_free": {"es": "Sin lácteos", "en": "Dairy free"},
    # Meal characteristics
    "quick": {"es": "Rápido", "en": "Quick"},
    "easy": {"es": "Fácil", "en": "Easy"},
    "meal_prep": {"es": "Apto para preparar", "en": "Meal prep friendly"},
    # Condition-specific
    "liver_friendly": {"es": "Apto para hígado graso", "en": "Liver friendly"},
    "pregnancy_safe": {"es": "Apto para embarazo", "en": "Pregnancy safe"},
    "lactation_safe": {"es": "Apto para lactancia", "en": "Lactation safe"},
}


def upgrade() -> None:
    rows = []
    for slug, translations in _VISION_ERRORS.items():
        for locale, value in translations.items():
            rows.append({"scope": "vision_error", "key": slug, "locale": locale, "value": value})
    for slug, translations in _TAGS.items():
        for locale, value in translations.items():
            rows.append({"scope": "tag", "key": slug, "locale": locale, "value": value})

    if rows:
        op.bulk_insert(
            sa.table(
                "i18n_translations",
                sa.column("scope", sa.Text),
                sa.column("key", sa.Text),
                sa.column("locale", sa.Text),
                sa.column("value", sa.Text),
            ),
            rows,
        )


def downgrade() -> None:
    for slug in _VISION_ERRORS:
        op.execute(
            sa.text(
                "DELETE FROM i18n_translations WHERE scope = 'vision_error' AND key = :k"
            ).bindparams(k=slug)
        )
    for slug in _TAGS:
        op.execute(
            sa.text(
                "DELETE FROM i18n_translations WHERE scope = 'tag' AND key = :k"
            ).bindparams(k=slug)
        )
