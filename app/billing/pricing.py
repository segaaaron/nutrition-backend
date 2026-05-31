"""Pricing tiers — PPP-adjusted by country.

Static table; updated quarterly. Values in minor units (cents) per month.
Currency conversion handled by the gateway at checkout time.
"""
from __future__ import annotations

from app.billing.domain import Plan

# country (ISO-2) → currency
COUNTRY_CURRENCY: dict[str, str] = {
    # Stripe regions — USD/CAD/EUR/GBP
    "US": "USD", "CA": "CAD", "GB": "GBP",
    "DE": "EUR", "FR": "EUR", "ES": "EUR", "IT": "EUR", "PT": "EUR", "NL": "EUR",
    # Mercado Pago — local LatAm currencies
    "AR": "ARS", "BR": "BRL", "CL": "CLP", "CO": "COP",
    "MX": "MXN", "PE": "PEN", "UY": "UYU",
}

# (plan, currency) → monthly cents
PRICE_CENTS: dict[tuple[Plan, str], int] = {
    (Plan.PREMIUM, "USD"):  999,
    (Plan.PREMIUM, "CAD"): 1399,
    (Plan.PREMIUM, "EUR"):  899,
    (Plan.PREMIUM, "GBP"):  799,
    # PPP-adjusted LatAm
    (Plan.PREMIUM, "MXN"):  9900,
    (Plan.PREMIUM, "BRL"):  2490,
    (Plan.PREMIUM, "ARS"): 499000,
    (Plan.PREMIUM, "CLP"):  4990,
    (Plan.PREMIUM, "COP"): 19900,
    (Plan.PREMIUM, "PEN"):  1990,
    (Plan.PREMIUM, "UYU"):  19900,
    (Plan.FAMILY,  "USD"): 1499,
    (Plan.FAMILY,  "CAD"): 1999,
    (Plan.FAMILY,  "EUR"): 1399,
    (Plan.FAMILY,  "GBP"): 1199,
    (Plan.FAMILY,  "MXN"): 14900,
    (Plan.FAMILY,  "BRL"):  3990,
    (Plan.FAMILY,  "ARS"): 749000,
    (Plan.FAMILY,  "CLP"):  7990,
    (Plan.FAMILY,  "COP"): 29900,
    (Plan.FAMILY,  "PEN"):  2990,
    (Plan.FAMILY,  "UYU"): 29900,
}


# Entitlements per plan (Sprint 8.A).
ENTITLEMENTS: dict[Plan, dict] = {
    Plan.FREE: {
        "max_photo_logs_per_day": 5,
        "coach_enabled": False,
        "recalibration_enabled": False,
        "grocery_enabled": True,
        "max_profiles": 1,
    },
    Plan.PREMIUM: {
        "max_photo_logs_per_day": None,  # unlimited
        "coach_enabled": True,
        "recalibration_enabled": True,
        "grocery_enabled": True,
        "max_profiles": 1,
    },
    Plan.FAMILY: {
        "max_photo_logs_per_day": None,
        "coach_enabled": True,
        "recalibration_enabled": True,
        "grocery_enabled": True,
        "max_profiles": 4,
    },
}


def currency_for(country: str) -> str:
    return COUNTRY_CURRENCY.get(country.upper(), "USD")


def price_for(plan: Plan, country: str) -> tuple[int, str]:
    cur = currency_for(country)
    cents = PRICE_CENTS.get((plan, cur), PRICE_CENTS[(plan, "USD")])
    return cents, cur
