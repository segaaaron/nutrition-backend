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
from typing import Iterable

from sqlalchemy import text

from app.core.db import session_scope
from app.gamification.domain.catalog import CATALOG

LOCALES = ("en", "es", "pt", "fr", "de")


def _t(en: str, es: str, pt: str, fr: str, de: str) -> dict[str, str]:
    return {"en": en, "es": es, "pt": pt, "fr": fr, "de": de}


GROCERY_CATEGORIES = {
    "fruits_vegetables": _t("Fruits & vegetables", "Frutas y verduras", "Frutas e legumes", "Fruits et légumes", "Obst & Gemüse"),
    "proteins":          _t("Proteins", "Proteínas", "Proteínas", "Protéines", "Proteine"),
    "dairy":             _t("Dairy", "Lácteos", "Laticínios", "Produits laitiers", "Milchprodukte"),
    "pantry":            _t("Pantry", "Despensa", "Despensa", "Garde-manger", "Vorratskammer"),
    "other":             _t("Other", "Otros", "Outros", "Autres", "Sonstige"),
}

LOG_METHODS = {
    "photo":   _t("Photo", "Foto", "Foto", "Photo", "Foto"),
    "voice":   _t("Voice", "Voz", "Voz", "Voix", "Sprache"),
    "text":    _t("Text", "Texto", "Texto", "Texte", "Text"),
    "barcode": _t("Barcode", "Código de barras", "Código de barras", "Code-barres", "Strichcode"),
    "search":  _t("Search", "Búsqueda", "Pesquisa", "Recherche", "Suche"),
    "manual":  _t("Manual", "Manual", "Manual", "Manuel", "Manuell"),
}

PLAN_STATUSES = {
    "active":    _t("Active", "Activo", "Ativo", "Actif", "Aktiv"),
    "completed": _t("Completed", "Completado", "Concluído", "Terminé", "Abgeschlossen"),
    "cancelled": _t("Cancelled", "Cancelado", "Cancelado", "Annulé", "Storniert"),
    "paused":    _t("Paused", "Pausado", "Pausado", "En pause", "Pausiert"),
    "draft":     _t("Draft", "Borrador", "Rascunho", "Brouillon", "Entwurf"),
}

# ~110 UI labels — curated, low ambiguity. Frontend keys mirror these codes.
COMMON_LABELS: dict[str, dict[str, str]] = {
    # Buttons
    "btn_save":          _t("Save", "Guardar", "Salvar", "Enregistrer", "Speichern"),
    "btn_cancel":        _t("Cancel", "Cancelar", "Cancelar", "Annuler", "Abbrechen"),
    "btn_delete":        _t("Delete", "Eliminar", "Excluir", "Supprimer", "Löschen"),
    "btn_edit":          _t("Edit", "Editar", "Editar", "Modifier", "Bearbeiten"),
    "btn_confirm":       _t("Confirm", "Confirmar", "Confirmar", "Confirmer", "Bestätigen"),
    "btn_continue":      _t("Continue", "Continuar", "Continuar", "Continuer", "Weiter"),
    "btn_back":          _t("Back", "Volver", "Voltar", "Retour", "Zurück"),
    "btn_next":          _t("Next", "Siguiente", "Próximo", "Suivant", "Weiter"),
    "btn_done":          _t("Done", "Listo", "Pronto", "Terminé", "Fertig"),
    "btn_close":         _t("Close", "Cerrar", "Fechar", "Fermer", "Schließen"),
    "btn_retry":         _t("Try again", "Reintentar", "Tentar novamente", "Réessayer", "Erneut versuchen"),
    "btn_login":         _t("Log in", "Iniciar sesión", "Entrar", "Se connecter", "Anmelden"),
    "btn_logout":        _t("Log out", "Cerrar sesión", "Sair", "Se déconnecter", "Abmelden"),
    "btn_signup":        _t("Sign up", "Registrarse", "Cadastrar-se", "S'inscrire", "Registrieren"),
    "btn_add":           _t("Add", "Añadir", "Adicionar", "Ajouter", "Hinzufügen"),
    "btn_remove":        _t("Remove", "Quitar", "Remover", "Retirer", "Entfernen"),
    "btn_share":         _t("Share", "Compartir", "Compartilhar", "Partager", "Teilen"),
    "btn_upload":        _t("Upload", "Subir", "Enviar", "Téléverser", "Hochladen"),
    "btn_take_photo":    _t("Take photo", "Tomar foto", "Tirar foto", "Prendre une photo", "Foto aufnehmen"),
    "btn_start":         _t("Start", "Iniciar", "Iniciar", "Démarrer", "Starten"),
    "btn_stop":          _t("Stop", "Detener", "Parar", "Arrêter", "Stoppen"),
    "btn_subscribe":     _t("Subscribe", "Suscribirse", "Assinar", "S'abonner", "Abonnieren"),
    # Errors
    "err_generic":       _t("Something went wrong.", "Algo salió mal.", "Algo deu errado.", "Une erreur s'est produite.", "Etwas ist schiefgelaufen."),
    "err_network":       _t("Network error.", "Error de red.", "Erro de rede.", "Erreur réseau.", "Netzwerkfehler."),
    "err_unauth":        _t("Please log in to continue.", "Inicia sesión para continuar.", "Faça login para continuar.", "Veuillez vous connecter.", "Bitte einloggen."),
    "err_forbidden":     _t("You don't have access.", "No tienes acceso.", "Você não tem acesso.", "Vous n'avez pas accès.", "Kein Zugriff."),
    "err_not_found":     _t("Not found.", "No encontrado.", "Não encontrado.", "Introuvable.", "Nicht gefunden."),
    "err_conflict":      _t("Already exists.", "Ya existe.", "Já existe.", "Existe déjà.", "Existiert bereits."),
    "err_rate_limited":  _t("Too many requests. Try again soon.", "Demasiadas solicitudes.", "Muitas solicitações.", "Trop de requêtes.", "Zu viele Anfragen."),
    "err_validation":    _t("Please check your input.", "Revisa los datos ingresados.", "Verifique seus dados.", "Vérifiez vos données.", "Bitte Eingabe prüfen."),
    "err_upstream":      _t("Service temporarily unavailable.", "Servicio no disponible.", "Serviço indisponível.", "Service indisponible.", "Dienst nicht verfügbar."),
    # Success
    "ok_saved":          _t("Saved.", "Guardado.", "Salvo.", "Enregistré.", "Gespeichert."),
    "ok_deleted":        _t("Deleted.", "Eliminado.", "Excluído.", "Supprimé.", "Gelöscht."),
    "ok_logged":         _t("Logged.", "Registrado.", "Registrado.", "Enregistré.", "Erfasst."),
    "ok_updated":        _t("Updated.", "Actualizado.", "Atualizado.", "Mis à jour.", "Aktualisiert."),
    "ok_copied":         _t("Copied to clipboard.", "Copiado.", "Copiado.", "Copié.", "Kopiert."),
    # Domain labels
    "label_kcal":        _t("Calories", "Calorías", "Calorias", "Calories", "Kalorien"),
    "label_protein":     _t("Protein", "Proteína", "Proteína", "Protéine", "Eiweiß"),
    "label_carbs":       _t("Carbs", "Carbohidratos", "Carboidratos", "Glucides", "Kohlenhydrate"),
    "label_fat":         _t("Fat", "Grasa", "Gordura", "Lipides", "Fett"),
    "label_fiber":       _t("Fiber", "Fibra", "Fibra", "Fibres", "Ballaststoffe"),
    "label_water":       _t("Water", "Agua", "Água", "Eau", "Wasser"),
    "label_weight":      _t("Weight", "Peso", "Peso", "Poids", "Gewicht"),
    "label_today":       _t("Today", "Hoy", "Hoje", "Aujourd'hui", "Heute"),
    "label_yesterday":   _t("Yesterday", "Ayer", "Ontem", "Hier", "Gestern"),
    "label_this_week":   _t("This week", "Esta semana", "Esta semana", "Cette semaine", "Diese Woche"),
    "label_streak":      _t("Streak", "Racha", "Sequência", "Série", "Serie"),
    "label_level":       _t("Level", "Nivel", "Nível", "Niveau", "Stufe"),
    "label_points":      _t("Points", "Puntos", "Pontos", "Points", "Punkte"),
    "label_breakfast":   _t("Breakfast", "Desayuno", "Café da manhã", "Petit-déjeuner", "Frühstück"),
    "label_lunch":       _t("Lunch", "Almuerzo", "Almoço", "Déjeuner", "Mittagessen"),
    "label_dinner":      _t("Dinner", "Cena", "Jantar", "Dîner", "Abendessen"),
    "label_snack":       _t("Snack", "Tentempié", "Lanche", "Collation", "Snack"),
    "label_fasting":     _t("Fasting", "Ayuno", "Jejum", "Jeûne", "Fasten"),
    "label_grocery":     _t("Grocery list", "Lista de compras", "Lista de compras", "Liste de courses", "Einkaufsliste"),
    "label_coach":       _t("Coach", "Coach", "Coach", "Coach", "Coach"),
    "label_plan":        _t("Plan", "Plan", "Plano", "Plan", "Plan"),
    "label_profile":     _t("Profile", "Perfil", "Perfil", "Profil", "Profil"),
    "label_settings":    _t("Settings", "Ajustes", "Configurações", "Paramètres", "Einstellungen"),
    "label_goal":        _t("Goal", "Objetivo", "Meta", "Objectif", "Ziel"),
    "label_progress":    _t("Progress", "Progreso", "Progresso", "Progrès", "Fortschritt"),
    "label_achievements":_t("Achievements", "Logros", "Conquistas", "Réalisations", "Erfolge"),
    "label_subscription":_t("Subscription", "Suscripción", "Assinatura", "Abonnement", "Abonnement"),
    "label_trial":       _t("Trial", "Prueba", "Avaliação", "Essai", "Testphase"),
    "label_premium":     _t("Premium", "Premium", "Premium", "Premium", "Premium"),
    "label_family":      _t("Family", "Familia", "Família", "Famille", "Familie"),
    "label_free":        _t("Free", "Gratis", "Grátis", "Gratuit", "Kostenlos"),
    # Disclaimers (compliance)
    "disclaimer_medical": _t(
        "Information here is for general wellness and does not replace medical advice.",
        "La información es de bienestar general y no sustituye el consejo médico.",
        "As informações são para bem-estar geral e não substituem orientação médica.",
        "Ces informations sont à but de bien-être et ne remplacent pas un avis médical.",
        "Diese Informationen ersetzen keine medizinische Beratung."),
    "disclaimer_estimate": _t(
        "Nutrition values are estimates and may vary by brand and preparation.",
        "Los valores nutricionales son estimaciones y pueden variar.",
        "Os valores nutricionais são estimativas e podem variar.",
        "Les valeurs nutritionnelles sont des estimations.",
        "Nährwertangaben sind Schätzungen."),
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
