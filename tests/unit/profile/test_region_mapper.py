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
        ("GB", "uk"),
        ("DE", "eu"),
        ("FR", "eu"),
        ("PT", "eu"),
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
        ("BR", "pt"),
        (None, "en"),
    ],
)
def test_country_to_locale(country, locale):
    assert country_to_locale(country) == locale
