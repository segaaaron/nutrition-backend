"""Achievements catalog — 30+ entries seeded by migration 0005.

Each achievement has:
  - code           stable canonical id (snake_case, immutable)
  - points         integer reward added to user total on unlock
  - icon           frontend asset slug
  - i18n           name + description in 5 supported locales
  - trigger        machine-readable rule for handlers (event + condition)

Triggers reference domain events by name. The check_achievements handler maps
events → eligible achievement codes via the catalog so handlers stay thin.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AchievementDef:
    code: str
    points: int
    icon: str
    trigger: str  # 'FoodLogged:first' | 'StreakBroken:7' | 'PlanCompleted:7' ...
    names: dict[str, str]
    descriptions: dict[str, str]


def _n(en: str, es: str, pt: str, fr: str, de: str) -> dict[str, str]:
    return {"en": en, "es": es, "pt": pt, "fr": fr, "de": de}


CATALOG: tuple[AchievementDef, ...] = (
    AchievementDef("first_meal_logged", 10, "spoon",
        "FoodLogged:first",
        _n("First bite",            "Primer registro",         "Primeira refeição",      "Premier repas",            "Erste Mahlzeit"),
        _n("Log your first meal.",  "Registra tu primera comida.","Registre sua primeira refeição.","Enregistrez votre premier repas.","Erfasse deine erste Mahlzeit.")),
    AchievementDef("streak_3d", 25, "fire",
        "DayCompleted:streak=3",
        _n("3-day streak",          "Racha de 3 días",         "Sequência de 3 dias",    "Série de 3 jours",         "3-Tage-Serie"),
        _n("Three perfect days in a row.","Tres días perfectos seguidos.","Três dias perfeitos seguidos.","Trois jours parfaits consécutifs.","Drei perfekte Tage in Folge.")),
    AchievementDef("streak_7d", 50, "fire",
        "DayCompleted:streak=7",
        _n("7-day streak",          "Racha de 7 días",         "Sequência de 7 dias",    "Série de 7 jours",         "7-Tage-Serie"),
        _n("A whole week on track.","Una semana entera.",      "Uma semana inteira.",    "Une semaine entière.",     "Eine ganze Woche.")),
    AchievementDef("streak_14d", 100, "fire",
        "DayCompleted:streak=14",
        _n("14-day streak",         "Racha de 14 días",        "Sequência de 14 dias",   "Série de 14 jours",        "14-Tage-Serie"),
        _n("Two weeks of consistency.","Dos semanas constantes.","Duas semanas de constância.","Deux semaines de constance.","Zwei Wochen Konsistenz.")),
    AchievementDef("streak_30d", 200, "fire",
        "DayCompleted:streak=30",
        _n("30-day streak",         "Racha de 30 días",        "Sequência de 30 dias",   "Série de 30 jours",        "30-Tage-Serie"),
        _n("One month strong.",     "Un mes firme.",           "Um mês firme.",          "Un mois solide.",          "Ein starker Monat.")),
    AchievementDef("streak_100d", 500, "fire",
        "DayCompleted:streak=100",
        _n("100-day streak",        "Racha de 100 días",       "Sequência de 100 dias",  "Série de 100 jours",       "100-Tage-Serie"),
        _n("Triple-digit dedication.","Dedicación de tres dígitos.","Dedicação de três dígitos.","Dévouement à trois chiffres.","Dreistellige Hingabe.")),
    AchievementDef("first_fasting_16h", 30, "moon",
        "FastingCompleted:achieved=true:method=16",
        _n("16-hour fast",          "Ayuno de 16h",            "Jejum de 16h",           "Jeûne de 16 h",            "16-Stunden-Fasten"),
        _n("Complete your first 16:8.","Completa tu primer 16:8.","Complete seu primeiro 16:8.","Terminez votre premier 16:8.","Erstes 16:8 abgeschlossen.")),
    AchievementDef("first_fasting_18h", 40, "moon",
        "FastingCompleted:achieved=true:method=18",
        _n("18-hour fast",          "Ayuno de 18h",            "Jejum de 18h",           "Jeûne de 18 h",            "18-Stunden-Fasten"),
        _n("Complete your first 18-hour fast.","Completa tu primer ayuno de 18h.","Complete seu primeiro jejum de 18h.","Terminez votre premier jeûne de 18 h.","Erstes 18-Stunden-Fasten.")),
    AchievementDef("first_fasting_20h", 60, "moon",
        "FastingCompleted:achieved=true:method=20",
        _n("20-hour fast",          "Ayuno de 20h",            "Jejum de 20h",           "Jeûne de 20 h",            "20-Stunden-Fasten"),
        _n("Complete your first 20-hour fast.","Completa tu primer ayuno de 20h.","Complete seu primeiro jejum de 20h.","Terminez votre premier jeûne de 20 h.","Erstes 20-Stunden-Fasten.")),
    AchievementDef("fasting_streak_7d", 100, "moon",
        "FastingCompleted:streak=7",
        _n("Fasting week",          "Semana de ayuno",         "Semana de jejum",        "Semaine de jeûne",         "Fastenwoche"),
        _n("Seven consecutive fasts.","Siete ayunos seguidos.","Sete jejuns seguidos.",  "Sept jeûnes consécutifs.", "Sieben Fasten in Folge.")),
    AchievementDef("protein_goal_7d", 80, "muscle",
        "ProteinGoalHit:7",
        _n("Protein week",          "Semana proteica",         "Semana proteica",        "Semaine protéinée",        "Proteinwoche"),
        _n("Hit protein target 7 days.","Cumple proteína 7 días.","Cumpra proteína por 7 dias.","Atteignez la cible de protéines 7 jours.","Eiweißziel 7 Tage erreicht.")),
    AchievementDef("water_goal_7d", 60, "drop",
        "WaterGoalHit:7",
        _n("Hydration week",        "Semana hidratada",        "Semana hidratada",       "Semaine hydratée",         "Hydrationswoche"),
        _n("Hit water target 7 days.","Cumple agua 7 días.",    "Cumpra água por 7 dias.","Atteignez la cible d’eau 7 jours.","Wasserziel 7 Tage erreicht.")),
    AchievementDef("first_recipe_swapped", 15, "shuffle",
        "RecipeSwapped:first",
        _n("Make it yours",         "A tu gusto",              "Do seu jeito",           "À votre goût",             "Nach deinem Geschmack"),
        _n("Swap your first recipe.","Cambia tu primera receta.","Troque sua primeira receita.","Échangez votre première recette.","Tausche dein erstes Rezept."),
    ),
    AchievementDef("plan_completed_week", 150, "calendar",
        "PlanCompleted:days=7",
        _n("Weekly winner",         "Ganador semanal",         "Vencedor semanal",       "Vainqueur de la semaine",  "Wochensieger"),
        _n("Finish a full weekly plan.","Termina un plan semanal.","Conclua um plano semanal.","Terminez un plan hebdomadaire.","Wochenplan abgeschlossen.")),
    AchievementDef("plan_completed_month", 500, "calendar",
        "PlanCompleted:days=30",
        _n("Monthly master",        "Maestro mensual",         "Mestre mensal",          "Maître du mois",           "Monatsmeister"),
        _n("Finish a full monthly plan.","Termina un plan mensual.","Conclua um plano mensal.","Terminez un plan mensuel.","Monatsplan abgeschlossen.")),
    AchievementDef("early_bird", 40, "sun",
        "EarlyBirdBreakfasts:3",
        _n("Early bird",            "Madrugador",              "Madrugador",             "Lève-tôt",                 "Frühaufsteher"),
        _n("Three breakfasts before 8 AM.","Tres desayunos antes de las 8.","Três cafés antes das 8h.","Trois petits-déjeuners avant 8 h.","Drei Frühstücke vor 8 Uhr.")),
    AchievementDef("weekend_warrior", 50, "shield",
        "WeekendComplete:both_days",
        _n("Weekend warrior",       "Guerrero del finde",      "Guerreiro do fim de semana","Guerrier du week-end",  "Wochenend-Krieger"),
        _n("Complete both weekend days.","Completa sábado y domingo.","Conclua sábado e domingo.","Complétez samedi et dimanche.","Samstag und Sonntag abgeschlossen.")),
    AchievementDef("meal_variety_30", 120, "leaf",
        "MealVariety:unique=30",
        _n("Variety chef",          "Chef variado",            "Chef variado",           "Chef varié",               "Vielfaltskoch"),
        _n("Try 30 different recipes.","Prueba 30 recetas distintas.","Experimente 30 receitas distintas.","Essayez 30 recettes différentes.","Probiere 30 verschiedene Rezepte.")),
    AchievementDef("vision_logs_10", 30, "camera",
        "VisionJobCompleted:n=10",
        _n("Snap & track",          "Foto y a la mesa",        "Foto e pronto",          "Photo et c’est tout",      "Foto und fertig"),
        _n("Log 10 meals via photo.","Registra 10 comidas por foto.","Registre 10 refeições por foto.","Enregistrez 10 repas par photo.","10 Mahlzeiten per Foto erfasst.")),
    AchievementDef("voice_logs_5", 20, "mic",
        "VoiceLogged:n=5",
        _n("Hands-free",            "Manos libres",            "Mãos livres",            "Mains libres",             "Freihändig"),
        _n("Log 5 meals by voice.", "Registra 5 comidas por voz.","Registre 5 refeições por voz.","Enregistrez 5 repas par la voix.","5 Mahlzeiten per Sprache erfasst.")),
    AchievementDef("first_weight_log", 10, "scale",
        "WeightLogged:first",
        _n("On the scale",          "Primer pesaje",           "Primeira pesagem",       "Première pesée",           "Erstes Wiegen"),
        _n("Log your first weight.","Registra tu primer peso.","Registre seu primeiro peso.","Enregistrez votre premier poids.","Erstes Gewicht erfasst.")),
    AchievementDef("weight_log_streak_14d", 70, "scale",
        "WeightLogged:streak=14",
        _n("Trend tracker",         "Sigue la tendencia",      "Acompanhe a tendência",  "Suivez la tendance",       "Trend-Tracker"),
        _n("Log weight 14 days.",   "Registra peso 14 días.",  "Registre peso por 14 dias.","Enregistrez le poids 14 jours.","Gewicht 14 Tage erfassen.")),
    AchievementDef("first_grocery_list", 15, "cart",
        "GroceryGenerated:first",
        _n("Smart shopper",         "Compra inteligente",      "Compra inteligente",     "Achat malin",              "Schlau einkaufen"),
        _n("Generate your first grocery list.","Genera tu primera lista de compras.","Gere sua primeira lista de compras.","Générez votre première liste de courses.","Erste Einkaufsliste erstellt.")),
    AchievementDef("kcal_within_tolerance_7d", 80, "target",
        "KcalWithinTolerance:7",
        _n("On target",             "En el objetivo",          "No alvo",                "Dans la cible",            "Im Ziel"),
        _n("Stay within calorie target 7 days.","Mantén el objetivo 7 días.","Mantenha o alvo por 7 dias.","Restez dans la cible 7 jours.","7 Tage im Kalorienziel."),
    ),
    AchievementDef("micronutrient_perfect_day", 90, "star",
        "MicroDayPerfect:once",
        _n("Micronutrient master",  "Maestro de micros",       "Mestre dos micros",      "Maître des micros",        "Mikronährstoff-Meister"),
        _n("Hit every micronutrient target in one day.","Cumple todos los micros en un día.","Cumpra todos os micros num dia.","Atteignez tous les micros en un jour.","Alle Mikros an einem Tag erreicht.")),
    AchievementDef("coach_first_chat", 10, "chat",
        "CoachMessageSent:first",
        _n("Hello coach",           "Hola coach",              "Olá coach",              "Bonjour coach",            "Hallo Coach"),
        _n("Send your first coach message.","Envía tu primer mensaje al coach.","Envie sua primeira mensagem ao coach.","Envoyez votre premier message au coach.","Sende deine erste Coach-Nachricht.")),
    AchievementDef("plan_recalibrated", 30, "compass",
        "PlanRecalibrated:first",
        _n("Adapt and conquer",     "Adapta y vence",          "Adapte e vença",         "Adaptez et triomphez",     "Anpassen und siegen"),
        _n("Your plan adapted to your real progress.","Tu plan se adaptó a tu progreso.","Seu plano se adaptou ao seu progresso.","Votre plan s'adapte à votre progression.","Dein Plan passt sich an.")),
    AchievementDef("photo_progress_first", 10, "photo",
        "ProgressPhotoUploaded:first",
        _n("Picture this",          "Primera foto",            "Primeira foto",          "Première photo",           "Erstes Foto"),
        _n("Upload your first progress photo.","Sube tu primera foto de progreso.","Envie sua primeira foto de progresso.","Téléchargez votre première photo.","Erstes Fortschrittsfoto.")),
    AchievementDef("comeback_kid", 25, "heart",
        "DayCompleted:after_gap=7",
        _n("Welcome back",          "Bienvenido de vuelta",    "Bem-vindo de volta",     "Bon retour",               "Willkommen zurück"),
        _n("Resume after a 7-day break.","Vuelve tras 7 días sin uso.","Volte após 7 dias parado.","Reprenez après 7 jours d'arrêt.","Nach 7 Tagen Pause zurück.")),
    AchievementDef("night_owl_3", 15, "moon-stars",
        "DinnerAfter21:3",
        _n("Night owl",             "Búho nocturno",           "Coruja noturna",         "Oiseau de nuit",           "Nachteule"),
        _n("Three dinners after 9 PM.","Tres cenas después de las 21.","Três jantares após as 21h.","Trois dîners après 21 h.","Drei Abendessen nach 21 Uhr.")),
    AchievementDef("level_5", 0, "trophy",
        "LevelUp:level=5",
        _n("Level 5",               "Nivel 5",                 "Nível 5",                "Niveau 5",                 "Stufe 5"),
        _n("Reach level 5.",        "Alcanza el nivel 5.",     "Alcance o nível 5.",     "Atteignez le niveau 5.",   "Erreiche Stufe 5.")),
    AchievementDef("level_10", 0, "trophy",
        "LevelUp:level=10",
        _n("Level 10",              "Nivel 10",                "Nível 10",               "Niveau 10",                "Stufe 10"),
        _n("Reach level 10.",       "Alcanza el nivel 10.",    "Alcance o nível 10.",    "Atteignez le niveau 10.",  "Erreiche Stufe 10.")),
)


def by_event(event_name: str) -> tuple[AchievementDef, ...]:
    return tuple(a for a in CATALOG if a.trigger.startswith(f"{event_name}:"))
