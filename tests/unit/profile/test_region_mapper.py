"""Region mapper tests."""

from __future__ import annotations

import pytest

from app.profile.domain.region_mapper import (
    country_to_locale,
    country_to_region,
)


@pytest.mark.parametrize(
    "country, region",
    [
        ("US", "us"),
        ("us", "us"),
        ("CA", "ca"),
        # EU/UK removed 2026-07-10 → unsupported countries default to "us".
        ("GB", "us"),
        ("DE", "us"),
        ("FR", "us"),
        ("PT", "us"),
        ("MX", "latam"),
        ("PE", "latam"),
        ("BR", "latam"),
        (None, "us"),
        ("XX", "us"),
    ],
)
def test_country_to_region(country, region):
    assert country_to_region(country) == region


@pytest.mark.parametrize(
    "country, locale",
    [
        ("US", "en"),
        ("CA", "en"),
        ("GB", "en"),
        ("DE", "en"),
        ("FR", "en"),
        ("MX", "es"),
        ("PE", "es"),
        # Only es/en supported → Brazil defaults to en (pt unsupported, and
        # Brazilians don't speak Spanish, so en is the neutral default).
        ("BR", "en"),
        (None, "en"),
    ],
)
def test_country_to_locale(country, locale):
    assert country_to_locale(country) == locale
