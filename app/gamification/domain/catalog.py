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


def _n(en: str, es: str) -> dict[str, str]:
    # Only es/en supported (owner decision 2026-07-10).
    return {"en": en, "es": es}


CATALOG: tuple[AchievementDef, ...] = (
    AchievementDef(
        "first_meal_logged",
        10,
        "spoon",
        "FoodLogged:first",
        _n("First bite", "Primer registro"),
        _n("Log your first meal.", "Registra tu primera comida."),
    ),
    AchievementDef(
        "streak_3d",
        25,
        "fire",
        "DayCompleted:streak=3",
        _n("3-day streak", "Racha de 3 días"),
        _n("Three perfect days in a row.", "Tres días perfectos seguidos."),
    ),
    AchievementDef(
        "streak_7d",
        50,
        "fire",
        "DayCompleted:streak=7",
        _n("7-day streak", "Racha de 7 días"),
        _n("A whole week on track.", "Una semana entera."),
    ),
    AchievementDef(
        "streak_14d",
        100,
        "fire",
        "DayCompleted:streak=14",
        _n("14-day streak", "Racha de 14 días"),
        _n("Two weeks of consistency.", "Dos semanas constantes."),
    ),
    AchievementDef(
        "streak_30d",
        200,
        "fire",
        "DayCompleted:streak=30",
        _n("30-day streak", "Racha de 30 días"),
        _n("One month strong.", "Un mes firme."),
    ),
    AchievementDef(
        "streak_100d",
        500,
        "fire",
        "DayCompleted:streak=100",
        _n("100-day streak", "Racha de 100 días"),
        _n("Triple-digit dedication.", "Dedicación de tres dígitos."),
    ),
    AchievementDef(
        "first_fasting_16h",
        30,
        "moon",
        "FastingCompleted:achieved=true:method=16",
        _n("16-hour fast", "Ayuno de 16h"),
        _n("Complete your first 16:8.", "Completa tu primer 16:8."),
    ),
    AchievementDef(
        "first_fasting_18h",
        40,
        "moon",
        "FastingCompleted:achieved=true:method=18",
        _n("18-hour fast", "Ayuno de 18h"),
        _n("Complete your first 18-hour fast.", "Completa tu primer ayuno de 18h."),
    ),
    AchievementDef(
        "first_fasting_20h",
        60,
        "moon",
        "FastingCompleted:achieved=true:method=20",
        _n("20-hour fast", "Ayuno de 20h"),
        _n("Complete your first 20-hour fast.", "Completa tu primer ayuno de 20h."),
    ),
    AchievementDef(
        "fasting_streak_7d",
        100,
        "moon",
        "FastingCompleted:streak=7",
        _n("Fasting week", "Semana de ayuno"),
        _n("Seven consecutive fasts.", "Siete ayunos seguidos."),
    ),
    AchievementDef(
        "protein_goal_7d",
        80,
        "muscle",
        "ProteinGoalHit:7",
        _n("Protein week", "Semana proteica"),
        _n("Hit protein target 7 days.", "Cumple proteína 7 días."),
    ),
    AchievementDef(
        "water_goal_7d",
        60,
        "drop",
        "WaterGoalHit:7",
        _n("Hydration week", "Semana hidratada"),
        _n("Hit water target 7 days.", "Cumple agua 7 días."),
    ),
    AchievementDef(
        "first_recipe_swapped",
        15,
        "shuffle",
        "RecipeSwapped:first",
        _n("Make it yours", "A tu gusto"),
        _n("Swap your first recipe.", "Cambia tu primera receta."),
    ),
    AchievementDef(
        "plan_completed_week",
        150,
        "calendar",
        "PlanCompleted:days=7",
        _n("Weekly winner", "Ganador semanal"),
        _n("Finish a full weekly plan.", "Termina un plan semanal."),
    ),
    AchievementDef(
        "plan_completed_month",
        500,
        "calendar",
        "PlanCompleted:days=30",
        _n("Monthly master", "Maestro mensual"),
        _n("Finish a full monthly plan.", "Termina un plan mensual."),
    ),
    AchievementDef(
        "early_bird",
        40,
        "sun",
        "EarlyBirdBreakfasts:3",
        _n("Early bird", "Madrugador"),
        _n("Three breakfasts before 8 AM.", "Tres desayunos antes de las 8."),
    ),
    AchievementDef(
        "weekend_warrior",
        50,
        "shield",
        "WeekendComplete:both_days",
        _n("Weekend warrior", "Guerrero del finde"),
        _n("Complete both weekend days.", "Completa sábado y domingo."),
    ),
    AchievementDef(
        "meal_variety_30",
        120,
        "leaf",
        "MealVariety:unique=30",
        _n("Variety chef", "Chef variado"),
        _n("Try 30 different recipes.", "Prueba 30 recetas distintas."),
    ),
    AchievementDef(
        "vision_logs_10",
        30,
        "camera",
        "VisionJobCompleted:n=10",
        _n("Snap & track", "Foto y a la mesa"),
        _n("Log 10 meals via photo.", "Registra 10 comidas por foto."),
    ),
    AchievementDef(
        "voice_logs_5",
        20,
        "mic",
        "VoiceLogged:n=5",
        _n("Hands-free", "Manos libres"),
        _n("Log 5 meals by voice.", "Registra 5 comidas por voz."),
    ),
    AchievementDef(
        "first_weight_log",
        10,
        "scale",
        "WeightLogged:first",
        _n("On the scale", "Primer pesaje"),
        _n("Log your first weight.", "Registra tu primer peso."),
    ),
    AchievementDef(
        "weight_log_streak_14d",
        70,
        "scale",
        "WeightLogged:streak=14",
        _n("Trend tracker", "Sigue la tendencia"),
        _n("Log weight 14 days.", "Registra peso 14 días."),
    ),
    AchievementDef(
        "first_grocery_list",
        15,
        "cart",
        "GroceryGenerated:first",
        _n("Smart shopper", "Compra inteligente"),
        _n("Generate your first grocery list.", "Genera tu primera lista de compras."),
    ),
    AchievementDef(
        "kcal_within_tolerance_7d",
        80,
        "target",
        "KcalWithinTolerance:7",
        _n("On target", "En el objetivo"),
        _n("Stay within calorie target 7 days.", "Mantén el objetivo 7 días."),
    ),
    AchievementDef(
        "micronutrient_perfect_day",
        90,
        "star",
        "MicroDayPerfect:once",
        _n("Micronutrient master", "Maestro de micros"),
        _n("Hit every micronutrient target in one day.", "Cumple todos los micros en un día."),
    ),
    AchievementDef(
        "coach_first_chat",
        10,
        "chat",
        "CoachMessageSent:first",
        _n("Hello coach", "Hola coach"),
        _n("Send your first coach message.", "Envía tu primer mensaje al coach."),
    ),
    AchievementDef(
        "plan_recalibrated",
        30,
        "compass",
        "PlanRecalibrated:first",
        _n("Adapt and conquer", "Adapta y vence"),
        _n("Your plan adapted to your real progress.", "Tu plan se adaptó a tu progreso."),
    ),
    AchievementDef(
        "photo_progress_first",
        10,
        "photo",
        "ProgressPhotoUploaded:first",
        _n("Picture this", "Primera foto"),
        _n("Upload your first progress photo.", "Sube tu primera foto de progreso."),
    ),
    AchievementDef(
        "comeback_kid",
        25,
        "heart",
        "DayCompleted:after_gap=7",
        _n("Welcome back", "Bienvenido de vuelta"),
        _n("Resume after a 7-day break.", "Vuelve tras 7 días sin uso."),
    ),
    AchievementDef(
        "night_owl_3",
        15,
        "moon-stars",
        "DinnerAfter21:3",
        _n("Night owl", "Búho nocturno"),
        _n("Three dinners after 9 PM.", "Tres cenas después de las 21."),
    ),
    AchievementDef(
        "level_5",
        0,
        "trophy",
        "LevelUp:level=5",
        _n("Level 5", "Nivel 5"),
        _n("Reach level 5.", "Alcanza el nivel 5."),
    ),
    AchievementDef(
        "level_10",
        0,
        "trophy",
        "LevelUp:level=10",
        _n("Level 10", "Nivel 10"),
        _n("Reach level 10.", "Alcanza el nivel 10."),
    ),
)


def by_event(event_name: str) -> tuple[AchievementDef, ...]:
    return tuple(a for a in CATALOG if a.trigger.startswith(f"{event_name}:"))
