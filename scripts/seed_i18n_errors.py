"""seed_i18n_errors.py — populate ``i18n_translations`` for RFC 7807 errors.

Phase 4 of docs/handoff/2026-06-05-i18n-runtime-locale-propagation-plan.md.

Idempotent UPSERT (``ON CONFLICT (scope, key, locale) DO UPDATE``). Safe to
run on every container boot — wired into ``docker/entrypoint.sh`` after
``alembic upgrade head``.

Rows seeded:

* scope ``"error"``  — every domain / business-rule error key, both
  ``<key>.title`` and ``<key>.detail`` entries, locales ``{es, en}``.
* scope ``"validation"`` — the most common pydantic ``type`` codes
  (``missing``, ``string_too_short``, ``int_parsing``, etc.).

Run:

    python -m scripts.seed_i18n_errors
"""

from __future__ import annotations

import asyncio
import sys
from typing import Final

from sqlalchemy import text

from app.core.db import session_scope
from app.shared.i18n import Locale

# ---------------------------------------------------------------------------
# Error key inventory — must stay in sync with:
#   * app/core/errors.py        — DomainError subclasses (type_slug)
#   * app/core/problem_details.py — _PLAN_RULE_TITLES + _classify_business_rule
#
# Schema: key -> { "title": {locale: str}, "detail": {locale: str} | None }
# When "detail" is None we ship the canonical EN raw detail (caller-provided).
# ---------------------------------------------------------------------------

_ErrorEntry = dict[str, dict[Locale, str] | None]

ERROR_MESSAGES: Final[dict[str, _ErrorEntry]] = {
    # --- Generic DomainError subclasses (handled by core/errors.py) ---
    "validation": {
        "title": {"es": "Error de validación", "en": "Validation failed"},
        "detail": {
            "es": "Uno o más campos no superaron la validación.",
            "en": "One or more fields failed validation.",
        },
    },
    "not_found": {
        "title": {"es": "No encontrado", "en": "Not found"},
        "detail": {
            "es": "Lo que buscas no existe o fue eliminado.",
            "en": "What you're looking for doesn't exist or was removed.",
        },
    },
    "conflict": {
        "title": {"es": "Ya existe", "en": "Already exists"},
        "detail": {
            "es": "Ya existe un registro con esos datos.",
            "en": "A record with that information already exists.",
        },
    },
    "gone": {
        "title": {"es": "Ya no disponible", "en": "No longer available"},
        "detail": {
            "es": "Este recurso ya no está disponible.",
            "en": "This resource is no longer available.",
        },
    },
    "locked": {
        "title": {"es": "No disponible ahora", "en": "Not available right now"},
        "detail": {
            "es": "Este recurso está bloqueado temporalmente. Intenta más tarde.",
            "en": "This resource is temporarily locked. Try again later.",
        },
    },
    "business_rule": {
        "title": {
            "es": "Acción no permitida",
            "en": "Action not allowed",
        },
        "detail": {
            "es": "Esta acción no está permitida en tu cuenta.",
            "en": "This action is not allowed for your account.",
        },
    },
    "illegal_transition": {
        "title": {
            "es": "Acción no válida en este momento",
            "en": "Action not valid right now",
        },
        "detail": {
            "es": "No puedes realizar esta acción en el estado actual. Intenta de nuevo.",
            "en": "You can't perform this action in the current state. Please try again.",
        },
    },
    "rate_limited": {
        "title": {"es": "Límite de peticiones excedido", "en": "Rate limit exceeded"},
        "detail": {
            "es": "Has superado el límite de solicitudes. Intenta más tarde.",
            "en": "You have exceeded the request limit. Try again later.",
        },
    },
    "cost_cap_exceeded": {
        "title": {"es": "Límite de costo alcanzado", "en": "Cost cap exceeded"},
        "detail": {
            "es": "Se alcanzó el tope de costo. Intenta más tarde.",
            "en": "Cost cap reached. Try again later.",
        },
    },
    "auth": {
        "title": {"es": "Error de autenticación", "en": "Authentication error"},
        "detail": {
            "es": "Hubo un problema con tu autenticación. Vuelve a iniciar sesión.",
            "en": "There was an authentication problem. Please sign in again.",
        },
    },
    "unauthenticated": {
        "title": {"es": "Sesión expirada", "en": "Session expired"},
        "detail": {
            "es": "Tu sesión expiró. Vuelve a iniciar sesión.",
            "en": "Your session has expired. Please sign in again.",
        },
    },
    "invalid_credentials": {
        "title": {"es": "Datos incorrectos", "en": "Incorrect credentials"},
        "detail": {
            "es": "El correo o la contraseña son incorrectos. Intenta de nuevo.",
            "en": "Your email or password is incorrect. Please try again.",
        },
    },
    "email_not_verified": {
        "title": {"es": "Email no verificado", "en": "Email not verified"},
        "detail": {
            "es": "Confirma tu email con el código que te enviamos antes de iniciar sesión.",
            "en": "Confirm your email with the code we sent before signing in.",
        },
    },
    "auth_ticket_invalid": {
        "title": {"es": "Código inválido", "en": "Invalid code"},
        "detail": {
            "es": "El código es inválido o ya fue usado. Solicita uno nuevo.",
            "en": "The code is invalid or already used. Request a new one.",
        },
    },
    "forbidden": {
        "title": {"es": "Sin permiso", "en": "No permission"},
        "detail": {
            "es": "No tienes permiso para realizar esta acción.",
            "en": "You don't have permission to perform this action.",
        },
    },
    "upstream": {
        "title": {"es": "Error de servicio externo", "en": "Upstream error"},
        "detail": {
            "es": "Un servicio externo respondió con error.",
            "en": "An upstream service returned an error.",
        },
    },
    "exif_leak": {
        "title": {
            "es": "Error al procesar la imagen",
            "en": "Image processing error",
        },
        "detail": {
            "es": "No pudimos procesar tu imagen correctamente. Intenta con otra foto.",
            "en": "We couldn't process your image correctly. Please try a different photo.",
        },
    },
    "internal": {
        "title": {"es": "Error del servidor", "en": "Server error"},
        "detail": {
            "es": "Ocurrió un error inesperado. Intenta de nuevo en unos segundos.",
            "en": "An unexpected error occurred. Please try again in a few seconds.",
        },
    },
    # --- BusinessRuleViolation classified rules (problem_details.py) ---
    "segment_unsupported_mvp": {
        "title": {
            "es": "Función no disponible aún",
            "en": "Feature not available yet",
        },
        "detail": {
            "es": "Esta función aún no está disponible para tu tipo de perfil. Pronto llegará.",
            "en": "This feature is not yet available for your profile type. Coming soon.",
        },
    },
    "profile_missing": {
        "title": {
            "es": "Falta información en tu perfil",
            "en": "Profile information missing",
        },
        "detail": {
            "es": "Falta completar un campo obligatorio en tu perfil. Revisa tus datos.",
            "en": "A required field is missing from your profile. Please review your information.",
        },
    },
    "allergen_unmapped_requires_review": {
        "title": {
            "es": "Alérgeno requiere revisión",
            "en": "Allergen requires review",
        },
        "detail": {
            "es": "Uno de tus alérgenos necesita revisión especializada. Contacta soporte.",
            "en": "One of your allergens needs specialist review. Contact support.",
        },
    },
    "trimester_required_for_pregnancy": {
        "title": {
            "es": "Falta el trimestre de embarazo",
            "en": "Pregnancy trimester missing",
        },
        "detail": {
            "es": "Por favor indica en qué trimestre de embarazo te encuentras.",
            "en": "Please indicate which trimester of pregnancy you are in.",
        },
    },
    "breastfeeding_status_required_for_lactation": {
        "title": {
            "es": "Falta el estado de lactancia",
            "en": "Breastfeeding status missing",
        },
        "detail": {
            "es": "Por favor indica si estás en período de lactancia.",
            "en": "Please indicate whether you are currently breastfeeding.",
        },
    },
    "height_required": {
        "title": {"es": "Falta tu altura", "en": "Height missing"},
        "detail": {
            "es": "Necesitamos tu altura para calcular tu plan. Agrégala en tu perfil.",
            "en": "We need your height to calculate your plan. Add it in your profile.",
        },
    },
    "onboarding_incomplete": {
        "title": {"es": "Perfil incompleto", "en": "Profile incomplete"},
        "detail": {
            "es": "Completa tu perfil para continuar usando la app.",
            "en": "Complete your profile to continue using the app.",
        },
    },
    "pediatric_outside_mvp_scope": {
        "title": {
            "es": "Perfil no disponible aún",
            "en": "Profile not available yet",
        },
        "detail": {
            "es": "Los planes para menores de edad estarán disponibles próximamente.",
            "en": "Plans for minors will be available soon.",
        },
    },
    "geriatric_requires_specialist_review": {
        "title": {
            "es": "Requiere revisión médica",
            "en": "Medical review required",
        },
        "detail": {
            "es": "Tu perfil requiere revisión por un especialista antes de generar un plan. Contacta soporte.",
            "en": "Your profile requires specialist review before generating a plan. Contact support.",
        },
    },
    # --- iOS user-facing detail messages (option B, 2026-06-07) ---
    # The error handler does a detail-specific i18n lookup first; if the
    # raised detail string matches a key here, the localised title + detail
    # below override the generic class message. iOS renders detail verbatim.
    "email_already_registered": {
        "title": {"es": "Cuenta ya registrada", "en": "Account already registered"},
        "detail": {
            "es": "Ya existe una cuenta con este email. Inicia sesión o usa otro email.",
            "en": "An account already exists with this email. Sign in or use a different email.",
        },
    },
    "password_too_short": {
        "title": {"es": "Contraseña muy corta", "en": "Password too short"},
        "detail": {
            "es": "La contraseña debe tener al menos 8 caracteres.",
            "en": "Password must be at least 8 characters long.",
        },
    },
    "account_deleted": {
        "title": {"es": "Cuenta eliminada", "en": "Account deleted"},
        "detail": {
            "es": "Esta cuenta fue eliminada. Crea una nueva o contacta soporte.",
            "en": "This account was deleted. Create a new one or contact support.",
        },
    },
    "no_active_plan": {
        "title": {"es": "Plan en preparación", "en": "Plan preparing"},
        "detail": {
            "es": "Tu plan se está generando. Inténtalo de nuevo en unos segundos.",
            "en": "Your plan is being generated. Try again in a few seconds.",
        },
    },
    "plan_generation_yielded_no_meals": {
        "title": {
            "es": "No se pudo generar tu plan",
            "en": "Could not generate your plan",
        },
        "detail": {
            "es": "No encontramos recetas que cumplan todas tus restricciones. Revisa tus alergias y condiciones, o contacta soporte.",
            "en": "We couldn't find recipes that meet all your restrictions. Review your allergies and conditions, or contact support.",
        },
    },
    "nutritional_goals_missing": {
        "title": {
            "es": "Falta completar tu perfil",
            "en": "Profile setup incomplete",
        },
        "detail": {
            "es": "Necesitamos tus datos completos (peso, altura, edad, meta) para generar el plan. Completa el onboarding.",
            "en": "We need your complete profile (weight, height, age, goal) to generate the plan. Complete onboarding first.",
        },
    },
    "nutritional_goals_unavailable": {
        "title": {
            "es": "Falta completar tu perfil",
            "en": "Profile setup incomplete",
        },
        "detail": {
            "es": "Antes de generar tu plan, completa el onboarding con tus datos (peso, altura, edad, meta de salud).",
            "en": "Before generating your plan, complete onboarding with your data (weight, height, age, health goal).",
        },
    },
    "profile_not_found": {
        "title": {
            "es": "Perfil no encontrado",
            "en": "Profile not found",
        },
        "detail": {
            "es": "Aún no has completado tu perfil. Completa el onboarding primero.",
            "en": "You haven't completed your profile yet. Complete onboarding first.",
        },
    },
    "no_candidates_for_meal": {
        "title": {
            "es": "Sin recetas para esta comida",
            "en": "No recipes for this meal",
        },
        "detail": {
            "es": "No encontramos recetas para esta comida que cumplan tus restricciones. Considera relajar alergias o condiciones.",
            "en": "We couldn't find recipes for this meal matching your restrictions. Consider easing allergies or conditions.",
        },
    },
    "region_audit_unavailable": {
        "title": {
            "es": "No se pudo actualizar tu región",
            "en": "Could not update your region",
        },
        "detail": {
            "es": "Hubo un problema temporal. Inténtalo de nuevo en unos segundos.",
            "en": "There was a temporary problem. Try again in a few seconds.",
        },
    },
    "duplicate_live_subscription": {
        "title": {
            "es": "Ya tienes una suscripción activa",
            "en": "You already have an active subscription",
        },
        "detail": {
            "es": "Ya tienes una suscripción vigente. Cancélala primero si quieres cambiar de plan.",
            "en": "You already have an active subscription. Cancel it first if you want to switch plans.",
        },
    },
    "grocery_generation_yielded_no_items": {
        "title": {
            "es": "No se pudo generar tu lista de compras",
            "en": "Could not generate your grocery list",
        },
        "detail": {
            "es": "No pudimos generar items para tu lista. Reintenta o contacta soporte.",
            "en": "We couldn't generate items for your list. Retry or contact support.",
        },
    },
    "user_creation_race": {
        "title": {
            "es": "Conflicto al crear la cuenta",
            "en": "Account creation conflict",
        },
        "detail": {
            "es": "Otra solicitud creó tu cuenta al mismo tiempo. Intenta iniciar sesión.",
            "en": "Another request created your account at the same time. Try signing in.",
        },
    },
    "otp_invalid": {
        "title": {"es": "Código incorrecto", "en": "Invalid code"},
        "detail": {
            "es": "El código que ingresaste es incorrecto. Verifica e intenta de nuevo.",
            "en": "The code you entered is incorrect. Verify and try again.",
        },
    },
    "otp_expired": {
        "title": {"es": "Código expirado", "en": "Code expired"},
        "detail": {
            "es": "El código expiró. Solicita uno nuevo.",
            "en": "The code expired. Request a new one.",
        },
    },
    "otp_locked": {
        "title": {"es": "Demasiados intentos", "en": "Too many attempts"},
        "detail": {
            "es": "Demasiados intentos fallidos. Espera unos minutos antes de reintentar.",
            "en": "Too many failed attempts. Wait a few minutes before retrying.",
        },
    },
}

# Pydantic v2 error `type` -> human messages.
# Keys MUST match pydantic's internal error type strings exactly (no
# transformation). See https://docs.pydantic.dev/latest/errors/validation_errors/.
VALIDATION_MESSAGES: Final[dict[str, dict[Locale, str]]] = {
    "missing": {
        "es": "Este campo es obligatorio.",
        "en": "This field is required.",
    },
    "string_too_short": {
        "es": "El texto es demasiado corto.",
        "en": "The string is too short.",
    },
    "string_too_long": {
        "es": "El texto es demasiado largo.",
        "en": "The string is too long.",
    },
    "string_pattern_mismatch": {
        "es": "El formato del texto no es válido.",
        "en": "String does not match the required pattern.",
    },
    "value_error": {
        "es": "Valor inválido.",
        "en": "Invalid value.",
    },
    "int_parsing": {
        "es": "Debe ser un número entero válido.",
        "en": "Must be a valid integer.",
    },
    "int_type": {
        "es": "Debe ser un número entero.",
        "en": "Must be an integer.",
    },
    "float_parsing": {
        "es": "Debe ser un número decimal válido.",
        "en": "Must be a valid number.",
    },
    "decimal_parsing": {
        "es": "Debe ser un valor decimal válido.",
        "en": "Must be a valid decimal.",
    },
    "bool_parsing": {
        "es": "Debe ser un valor booleano.",
        "en": "Must be a boolean value.",
    },
    "bool_type": {
        "es": "Debe ser un valor booleano.",
        "en": "Must be a boolean value.",
    },
    "uuid_parsing": {
        "es": "Debe ser un UUID válido.",
        "en": "Must be a valid UUID.",
    },
    "datetime_parsing": {
        "es": "Debe ser una fecha/hora válida.",
        "en": "Must be a valid datetime.",
    },
    "date_parsing": {
        "es": "Debe ser una fecha válida.",
        "en": "Must be a valid date.",
    },
    "enum": {
        "es": "Valor no permitido para este campo.",
        "en": "Value not allowed for this field.",
    },
    "greater_than": {
        "es": "El valor es demasiado pequeño.",
        "en": "Value is too small.",
    },
    "greater_than_equal": {
        "es": "El valor es demasiado pequeño.",
        "en": "Value is too small.",
    },
    "less_than": {
        "es": "El valor es demasiado grande.",
        "en": "Value is too large.",
    },
    "less_than_equal": {
        "es": "El valor es demasiado grande.",
        "en": "Value is too large.",
    },
    "extra_forbidden": {
        "es": "Campo no permitido.",
        "en": "Extra field not permitted.",
    },
    "json_invalid": {
        "es": "JSON inválido.",
        "en": "Invalid JSON.",
    },
    "model_type": {
        "es": "Tipo de objeto inválido.",
        "en": "Invalid object type.",
    },
    "list_type": {
        "es": "Debe ser una lista.",
        "en": "Must be a list.",
    },
    "dict_type": {
        "es": "Debe ser un objeto.",
        "en": "Must be an object.",
    },
    "email": {
        "es": "Email inválido.",
        "en": "Invalid email address.",
    },
}


_UPSERT_SQL = text(
    """
    INSERT INTO i18n_translations (scope, key, locale, value)
    VALUES (:scope, :key, :locale, :value)
    ON CONFLICT (scope, key, locale)
    DO UPDATE SET value = EXCLUDED.value, updated_at = now()
    """
)


def _expand_error_rows() -> list[dict[str, str]]:
    """Flatten ERROR_MESSAGES into individual ``i18n_translations`` rows.

    Each error key contributes 2 keys (``.title`` + ``.detail``) × 2 locales
    when ``detail`` is populated, else 1 key × 2 locales.
    """
    rows: list[dict[str, str]] = []
    for i18n_key, entry in ERROR_MESSAGES.items():
        title_map = entry["title"]
        assert title_map is not None, f"missing title for {i18n_key}"
        for locale, value in title_map.items():
            rows.append(
                {
                    "scope": "error",
                    "key": f"{i18n_key}.title",
                    "locale": locale,
                    "value": value,
                }
            )
        detail_map = entry["detail"]
        if detail_map is not None:
            for locale, value in detail_map.items():
                rows.append(
                    {
                        "scope": "error",
                        "key": f"{i18n_key}.detail",
                        "locale": locale,
                        "value": value,
                    }
                )
    return rows


def _expand_validation_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for ptype, locales in VALIDATION_MESSAGES.items():
        for locale, value in locales.items():
            rows.append(
                {
                    "scope": "validation",
                    "key": ptype,
                    "locale": locale,
                    "value": value,
                }
            )
    return rows


async def seed() -> int:
    """UPSERT all error + validation rows. Returns total row count."""
    rows = _expand_error_rows() + _expand_validation_rows()
    async with session_scope() as session:
        for row in rows:
            await session.execute(_UPSERT_SQL, row)
    return len(rows)


def main() -> int:
    count = asyncio.run(seed())
    print(f"[seed_i18n_errors] upserted {count} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
