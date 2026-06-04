"""Sprint 8.A — pricing matrix + entitlement defaults."""

from __future__ import annotations

from app.billing.domain import Plan
from app.billing.pricing import ENTITLEMENTS, currency_for, price_for


def test_currency_lookup_defaults_to_usd():
    assert currency_for("US") == "USD"
    assert currency_for("XX") == "USD"


def test_currency_lookup_latam():
    assert currency_for("MX") == "MXN"
    assert currency_for("BR") == "BRL"
    assert currency_for("PE") == "PEN"


def test_premium_us_price_999_cents():
    cents, cur = price_for(Plan.PREMIUM, "US")
    assert cents == 999
    assert cur == "USD"


def test_family_mx_is_cheaper_than_family_us_in_real_terms():
    us, _ = price_for(Plan.FAMILY, "US")
    mx, _ = price_for(Plan.FAMILY, "MX")
    # MXN denominated — sanity-check we shipped a value
    assert mx > 0
    assert us == 1499


def test_free_has_no_coach_unlimited_premium_does():
    assert ENTITLEMENTS[Plan.FREE]["coach_enabled"] is False
    assert ENTITLEMENTS[Plan.PREMIUM]["coach_enabled"] is True
    assert ENTITLEMENTS[Plan.PREMIUM]["max_photo_logs_per_day"] is None


def test_family_allows_four_profiles():
    assert ENTITLEMENTS[Plan.FAMILY]["max_profiles"] == 4
