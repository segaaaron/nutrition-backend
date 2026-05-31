"""Metric ↔ Imperial unit conversion + locale-aware formatting.

US default = imperial; rest of supported locales default to metric. The user
profile's `units` override wins over the locale default.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal

from app.shared.domain.value_objects import Locale

Unit = Literal["kg", "lb", "cm", "in", "ml", "fl_oz", "c_temp", "f_temp"]

_KG_PER_LB = Decimal("0.45359237")
_CM_PER_IN = Decimal("2.54")
_ML_PER_FLOZ = Decimal("29.5735295625")


def kg_to_lb(kg: Decimal) -> Decimal:
    return (kg / _KG_PER_LB).quantize(Decimal("0.1"))


def lb_to_kg(lb: Decimal) -> Decimal:
    return (lb * _KG_PER_LB).quantize(Decimal("0.01"))


def cm_to_in(cm: Decimal) -> Decimal:
    return (cm / _CM_PER_IN).quantize(Decimal("0.1"))


def in_to_cm(inches: Decimal) -> Decimal:
    return (inches * _CM_PER_IN).quantize(Decimal("0.1"))


def ml_to_floz(ml: Decimal) -> Decimal:
    return (ml / _ML_PER_FLOZ).quantize(Decimal("0.1"))


def floz_to_ml(floz: Decimal) -> Decimal:
    return (floz * _ML_PER_FLOZ).quantize(Decimal("0.1"))


def c_to_f(c: Decimal) -> Decimal:
    return (c * Decimal("1.8") + Decimal("32")).quantize(Decimal("0.1"))


def f_to_c(f: Decimal) -> Decimal:
    return ((f - Decimal("32")) / Decimal("1.8")).quantize(Decimal("0.1"))


def default_units_for_locale(locale: Locale) -> Literal["metric", "imperial"]:
    # US is the only mainstream imperial market in our supported set.
    return "imperial" if locale == "en" else "metric"


def format_for_locale(value: Decimal, unit: Unit, locale: Locale) -> str:
    """Lightweight formatter. Replace with Babel when ICU pluralisation lands."""
    sep = "," if locale in {"es", "pt", "fr", "de"} else "."
    s = f"{value}".replace(".", sep)
    return f"{s} {unit.replace('_', ' ')}"
