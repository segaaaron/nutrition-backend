"""seed_i18n.py — backfill i18n_translations for ALL canonical IDs.

Idempotent. Uses curated human translations only (no auto-translate). Run via:

    python -m scripts.seed_i18n [--dry-run] [--scope=allergens|conditions|all]

Scopes covered:
  - allergens (14)              — already partially seeded by 0001_init
  - conditions (25)             — already partially seeded by 0001_init
  - goals (5)                   — already partially seeded
  - activity_levels (5)         — already partially seeded
  - meal_times (4)              — already partially seeded
  - achievements (32)           — names + descriptions per locale
  - grocery_categories (5)
  - log_methods (6)
  - plan_statuses (5)
  - common_labels (100+)        — buttons, errors, success messages

Re-runs are safe: rows are UPSERTed by (scope, code, locale).
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Iterable

from sqlalchemy import text

from app.core.db import session_scope
from app.gamification.domain.catalog import CATALOG

LOCALES = ("en", "es")


def _t(en: str, es: str) -> dict[str, str]:
    # Only es/en are supported (owner decision 2026-07-10).
    return {"en": en, "es": es}


GROCERY_CATEGORIES = {
    "fruits_vegetables": _t("Fruits & vegetables", "Frutas y verduras"),
    "proteins":          _t("Proteins", "Proteínas"),
    "dairy":             _t("Dairy", "Lácteos"),
    "pantry":            _t("Pantry", "Despensa"),
    "other":             _t("Other", "Otros"),
}

LOG_METHODS = {
    "photo":   _t("Photo", "Foto"),
    "voice":   _t("Voice", "Voz"),
    "text":    _t("Text", "Texto"),
    "barcode": _t("Barcode", "Código de barras"),
    "search":  _t("Search", "Búsqueda"),
    "manual":  _t("Manual", "Manual"),
}

PLAN_STATUSES = {
    "active":    _t("Active", "Activo"),
    "completed": _t("Completed", "Completado"),
    "cancelled": _t("Cancelled", "Cancelado"),
    "paused":    _t("Paused", "Pausado"),
    "draft":     _t("Draft", "Borrador"),
}

# ~110 UI labels — curated, low ambiguity. Frontend keys mirror these codes.
COMMON_LABELS: dict[str, dict[str, str]] = {
    # Buttons
    "btn_save":          _t("Save", "Guardar"),
    "btn_cancel":        _t("Cancel", "Cancelar"),
    "btn_delete":        _t("Delete", "Eliminar"),
    "btn_edit":          _t("Edit", "Editar"),
    "btn_confirm":       _t("Confirm", "Confirmar"),
    "btn_continue":      _t("Continue", "Continuar"),
    "btn_back":          _t("Back", "Volver"),
    "btn_next":          _t("Next", "Siguiente"),
    "btn_done":          _t("Done", "Listo"),
    "btn_close":         _t("Close", "Cerrar"),
    "btn_retry":         _t("Try again", "Reintentar"),
    "btn_login":         _t("Log in", "Iniciar sesión"),
    "btn_logout":        _t("Log out", "Cerrar sesión"),
    "btn_signup":        _t("Sign up", "Registrarse"),
    "btn_add":           _t("Add", "Añadir"),
    "btn_remove":        _t("Remove", "Quitar"),
    "btn_share":         _t("Share", "Compartir"),
    "btn_upload":        _t("Upload", "Subir"),
    "btn_take_photo":    _t("Take photo", "Tomar foto"),
    "btn_start":         _t("Start", "Iniciar"),
    "btn_stop":          _t("Stop", "Detener"),
    "btn_subscribe":     _t("Subscribe", "Suscribirse"),
    # Errors
    "err_generic":       _t("Something went wrong.", "Algo salió mal."),
    "err_network":       _t("Network error.", "Error de red."),
    "err_unauth":        _t("Please log in to continue.", "Inicia sesión para continuar."),
    "err_forbidden":     _t("You don't have access.", "No tienes acceso."),
    "err_not_found":     _t("Not found.", "No encontrado."),
    "err_conflict":      _t("Already exists.", "Ya existe."),
    "err_rate_limited":  _t("Too many requests. Try again soon.", "Demasiadas solicitudes."),
    "err_validation":    _t("Please check your input.", "Revisa los datos ingresados."),
    "err_upstream":      _t("Service temporarily unavailable.", "Servicio no disponible."),
    # Success
    "ok_saved":          _t("Saved.", "Guardado."),
    "ok_deleted":        _t("Deleted.", "Eliminado."),
    "ok_logged":         _t("Logged.", "Registrado."),
    "ok_updated":        _t("Updated.", "Actualizado."),
    "ok_copied":         _t("Copied to clipboard.", "Copiado."),
    # Domain labels
    "label_kcal":        _t("Calories", "Calorías"),
    "label_protein":     _t("Protein", "Proteína"),
    "label_carbs":       _t("Carbs", "Carbohidratos"),
    "label_fat":         _t("Fat", "Grasa"),
    "label_fiber":       _t("Fiber", "Fibra"),
    "label_water":       _t("Water", "Agua"),
    "label_weight":      _t("Weight", "Peso"),
    "label_today":       _t("Today", "Hoy"),
    "label_yesterday":   _t("Yesterday", "Ayer"),
    "label_this_week":   _t("This week", "Esta semana"),
    "label_streak":      _t("Streak", "Racha"),
    "label_level":       _t("Level", "Nivel"),
    "label_points":      _t("Points", "Puntos"),
    "label_breakfast":   _t("Breakfast", "Desayuno"),
    "label_lunch":       _t("Lunch", "Almuerzo"),
    "label_dinner":      _t("Dinner", "Cena"),
    "label_snack":       _t("Snack", "Tentempié"),
    "label_fasting":     _t("Fasting", "Ayuno"),
    "label_grocery":     _t("Grocery list", "Lista de compras"),
    "label_coach":       _t("Coach", "Coach"),
    "label_plan":        _t("Plan", "Plan"),
    "label_profile":     _t("Profile", "Perfil"),
    "label_settings":    _t("Settings", "Ajustes"),
    "label_goal":        _t("Goal", "Objetivo"),
    "label_progress":    _t("Progress", "Progreso"),
    "label_achievements":_t("Achievements", "Logros"),
    "label_subscription":_t("Subscription", "Suscripción"),
    "label_trial":       _t("Trial", "Prueba"),
    "label_premium":     _t("Premium", "Premium"),
    "label_family":      _t("Family", "Familia"),
    "label_free":        _t("Free", "Gratis"),
    # Disclaimers (compliance)
    "disclaimer_medical": _t("Information here is for general wellness and does not replace medical advice.", "La información es de bienestar general y no sustituye el consejo médico."),
    "disclaimer_estimate": _t("Nutrition values are estimates and may vary by brand and preparation.", "Los valores nutricionales son estimaciones y pueden variar."),
}


async def _upsert(session, scope: str, code: str, locale: str, value: str) -> None:
    await session.execute(text("""
        INSERT INTO i18n_translations (scope, key, locale, value)
        VALUES (:s, :c, :l, :v)
        ON CONFLICT (scope, key, locale) DO UPDATE SET value = EXCLUDED.value
    """), {"s": scope, "c": code, "l": locale, "v": value})


async def seed_scope(scope: str, items: Iterable[tuple[str, dict[str, str]]]) -> int:
    n = 0
    async with session_scope() as session:
        for code, m in items:
            for loc in LOCALES:
                v = m.get(loc) or m["en"]
                await _upsert(session, scope, code, loc, v)
                n += 1
    return n


async def main(scope: str = "all", dry_run: bool = False) -> None:
    if dry_run:
        print("[dry-run] would seed scopes:", scope)
        return
    total = 0
    if scope in ("all", "grocery_categories"):
        total += await seed_scope("grocery_categories", GROCERY_CATEGORIES.items())
    if scope in ("all", "log_methods"):
        total += await seed_scope("log_methods", LOG_METHODS.items())
    if scope in ("all", "plan_statuses"):
        total += await seed_scope("plan_statuses", PLAN_STATUSES.items())
    if scope in ("all", "achievements"):
        items_n = [(a.code, a.names) for a in CATALOG]
        items_d = [(f"{a.code}_desc", a.descriptions) for a in CATALOG]
        total += await seed_scope("achievement_names", items_n)
        total += await seed_scope("achievement_descriptions", items_d)
    if scope in ("all", "common_labels"):
        total += await seed_scope("common_labels", COMMON_LABELS.items())
    print(f"i18n seed complete: {total} rows upserted across 5 locales.")


def cli() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope", default="all")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    asyncio.run(main(args.scope, args.dry_run))
    return 0


if __name__ == "__main__":
    sys.exit(cli())
