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
        "title": {"es": "Recurso no encontrado", "en": "Resource not found"},
        "detail": None,
    },
    "conflict": {
        "title": {"es": "Conflicto de recurso", "en": "Resource conflict"},
        "detail": None,
    },
    "gone": {
        "title": {"es": "Recurso eliminado", "en": "Resource gone"},
        "detail": None,
    },
    "locked": {
        "title": {"es": "Recurso bloqueado", "en": "Resource locked"},
        "detail": None,
    },
    "business_rule": {
        "title": {
            "es": "Violación de regla de negocio",
            "en": "Business rule violation",
        },
        "detail": None,
    },
    "illegal_transition": {
        "title": {
            "es": "Transición de estado no permitida",
            "en": "Illegal state transition",
        },
        "detail": None,
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
        "detail": None,
    },
    "unauthenticated": {
        "title": {"es": "Autenticación requerida", "en": "Authentication required"},
        "detail": {
            "es": "Token faltante o inválido.",
            "en": "Missing or invalid token.",
        },
    },
    "invalid_credentials": {
        "title": {"es": "Credenciales inválidas", "en": "Invalid credentials"},
        "detail": {
            "es": "Email o contraseña incorrectos.",
            "en": "Incorrect email or password.",
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
        "title": {"es": "Ticket de autenticación inválido", "en": "Auth ticket invalid"},
        "detail": None,
    },
    "forbidden": {
        "title": {"es": "Acceso denegado", "en": "Forbidden"},
        "detail": {
            "es": "No tienes permiso para acceder a este recurso.",
            "en": "You do not have permission to access this resource.",
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
            "es": "Error de verificación EXIF",
            "en": "EXIF strip verification failed",
        },
        "detail": None,
    },
    "internal": {
        "title": {"es": "Error interno", "en": "Internal error"},
        "detail": None,
    },
    # --- BusinessRuleViolation classified rules (problem_details.py) ---
    "segment_unsupported_mvp": {
        "title": {
            "es": "Segmento de usuario no soportado en MVP",
            "en": "User segment not supported in MVP",
        },
        "detail": None,
    },
    "profile_missing": {
        "title": {
            "es": "Falta un campo obligatorio del perfil",
            "en": "Required profile field missing",
        },
        "detail": None,
    },
    "allergen_unmapped_requires_review": {
        "title": {
            "es": "Alérgeno no mapeado — requiere revisión especializada",
            "en": "Allergen unmapped — specialist review required",
        },
        "detail": None,
    },
    "trimester_required_for_pregnancy": {
        "title": {
            "es": "Se requiere el trimestre para embarazo",
            "en": "Trimester required for pregnancy",
        },
        "detail": None,
    },
    "breastfeeding_status_required_for_lactation": {
        "title": {
            "es": "Se requiere el estado de lactancia",
            "en": "Breastfeeding status required for lactation",
        },
        "detail": None,
    },
    "height_required": {
        "title": {"es": "Se requiere la altura", "en": "Height required"},
        "detail": None,
    },
    "onboarding_incomplete": {
        "title": {"es": "Onboarding incompleto", "en": "Onboarding incomplete"},
        "detail": {
            "es": "Completa tu perfil antes de continuar.",
            "en": "Complete your profile before continuing.",
        },
    },
    "pediatric_outside_mvp_scope": {
        "title": {
            "es": "Usuarios pediátricos fuera del alcance del MVP",
            "en": "Pediatric users outside MVP scope",
        },
        "detail": None,
    },
    "geriatric_requires_specialist_review": {
        "title": {
            "es": "Usuarios geriátricos requieren revisión especializada",
            "en": "Geriatric users require specialist review",
        },
        "detail": None,
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
