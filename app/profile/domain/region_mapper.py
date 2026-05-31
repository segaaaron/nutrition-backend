"""Derive `region` and default `locale` from ISO-3166-1 alpha-2 country code.

Pure domain logic — the canonical source is the `regions` table seeded by
migration 0001, but we mirror the mapping here to keep onboarding latency
sub-ms (no DB roundtrip) and let tests run without a DB.
"""
from __future__ import annotations

from typing import Final

_COUNTRY_TO_REGION: Final[dict[str, str]] = {}
_REGION_DEFAULT_LOCALE: Final[dict[str, str]] = {
    "us": "en", "ca": "en", "eu": "en", "uk": "en", "latam": "es",
}

# US
_COUNTRY_TO_REGION["US"] = "us"
# CA
_COUNTRY_TO_REGION["CA"] = "ca"
# UK
_COUNTRY_TO_REGION["GB"] = "uk"
# EU
for c in ["DE", "FR", "IT", "ES", "PT", "NL", "BE", "AT", "IE", "FI", "SE", "DK",
          "PL", "CZ", "GR", "RO", "HU", "BG", "HR", "SI", "SK", "LU", "MT", "CY",
          "EE", "LV", "LT"]:
    _COUNTRY_TO_REGION[c] = "eu"
# LATAM
for c in ["MX", "PE", "CO", "AR", "CL", "BR", "VE", "EC", "UY", "PY", "BO", "CR",
          "PA", "GT", "HN", "SV", "NI", "DO", "PR"]:
    _COUNTRY_TO_REGION[c] = "latam"


def country_to_region(country: str | None) -> str:
    """Defaults to 'us' (safest allergen-disclosure default) when unknown."""
    if not country:
        return "us"
    return _COUNTRY_TO_REGION.get(country.upper(), "us")


def region_default_locale(region: str) -> str:
    return _REGION_DEFAULT_LOCALE.get(region, "en")


def country_to_locale(country: str | None) -> str:
    """One-shot derivation. Brazil maps to 'pt' (overrides region 'es')."""
    if country and country.upper() == "BR":
        return "pt"
    return region_default_locale(country_to_region(country))
