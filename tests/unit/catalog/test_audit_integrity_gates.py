"""Lock the Tier 2 integrity gates added after the 2026-08-04 catalog audit.

Tier 1 (NULL ratios) reported the catalog GREEN while it carried sodium_mg=0 on
1,437 recipes, 131 undeclared allergens and zero recipes for the Canadian
market. These tests fence the gate set so a later refactor cannot quietly drop
a check and restore that blind spot.
"""

from __future__ import annotations

from decimal import Decimal

from scripts.catalog_completeness_audit import (
    MACRO_TOLERANCE,
    POOL_HARD_MIN,
    POOL_WARN_MIN,
    SLOT_KCAL_BANDS,
    SUPPORTED_CONDITIONS,
    SUPPORTED_MARKETS,
    IntegrityCheck,
)

# Every gate that must exist. Removing one requires editing this list, which
# forces the reviewer to justify narrowing the protected surface.
REQUIRED_GATES = {
    "safety_columns_all_zero",
    "sodium_zero",
    "added_sugar_missing",
    "added_sugar_exceeds_total",
    "atwater_mismatch",
    "recipe_without_components",
    "region_tag_unsupported",
    "region_missing",
    "market_empty",
    "recommended_conditions_unsupported",
    "contraindicated_conditions_unsupported",
    "allergen_undeclared",
    "ingredient_unresolved",
    "kcal_outside_slot_band",
    "pool_below_hard_minimum",
    "pool_below_buffer",
}


def test_supported_markets_match_region_mapper() -> None:
    """`region_mapper.country_to_region` can only ever emit these three. A
    market missing here is a market whose users get no plan."""
    from app.profile.domain.region_mapper import country_to_region

    emitted = {country_to_region(c) for c in ("US", "CA", "MX", "PE", "BO", "XX", None)}
    assert emitted <= set(SUPPORTED_MARKETS)
    assert set(SUPPORTED_MARKETS) == {"latam", "us", "ca"}


def test_supported_conditions_are_the_closed_set() -> None:
    """REGLA #0.5.C: exactly three, and they must match the onboarding enum."""
    from typing import get_args

    from app.profile.presentation.schemas import MobileCondition

    assert set(SUPPORTED_CONDITIONS) == {"fatty_liver", "pregnancy", "lactation"}
    # MobileCondition is the API enforcement point: the DB condition_enum still
    # carries the retired values, so the catalog must be gated on this set.
    assert set(SUPPORTED_CONDITIONS) == set(get_args(MobileCondition))


def test_macro_tolerance_matches_spec() -> None:
    """Single source of truth is spec §6; the audit mirrors it to avoid an app
    import at boot. Drift between the two would let bad macros through."""
    assert MACRO_TOLERANCE == Decimal("0.02")


def test_pool_minimums_encode_the_no_repeat_rule() -> None:
    """REGLA #0.5.D forbids repeating a recipe inside a plan window, so a
    7-day plan needs 21 distinct recipes per slot; 63 is the 3x buffer."""
    assert POOL_HARD_MIN == 21
    assert POOL_WARN_MIN == 3 * POOL_HARD_MIN


def test_every_slot_has_a_kcal_band() -> None:
    assert set(SLOT_KCAL_BANDS) == {"breakfast", "lunch", "dinner", "snack"}
    for slot, (lo, hi) in SLOT_KCAL_BANDS.items():
        assert 0 < lo < hi, slot


def test_integrity_check_passes_only_at_zero_violations() -> None:
    assert IntegrityCheck("x", "d", violations=0).passed
    assert not IntegrityCheck("x", "d", violations=1).passed


def test_gate_set_is_locked() -> None:
    """Fence the gate names. This mirrors the CRITICAL_COLUMNS lock: shrinking
    the set must be a deliberate, reviewed act."""
    import inspect

    from scripts import catalog_completeness_audit as audit

    source = inspect.getsource(audit._integrity_checks)
    missing = {g for g in REQUIRED_GATES if f'"{g}"' not in source}
    assert not missing, (
        f"integrity gates disappeared from the audit: {sorted(missing)}. "
        "Each one exists because that exact defect reached PROD — restore it "
        "or document why the catalog no longer needs it."
    )


def test_fatal_gates_block_ci_and_warnings_do_not() -> None:
    """`sodium_zero` is a warning (a fruit-and-nut snack genuinely rounds to
    0 mg); the clobber signature is fatal. Getting this backwards would either
    spam CI or hide the real bug."""
    fatal = IntegrityCheck("safety_columns_all_zero", "d", violations=1, fatal=True)
    warn = IntegrityCheck("sodium_zero", "d", violations=2, fatal=False)
    checks = [fatal, warn]
    assert any(c.fatal and not c.passed for c in checks)
    assert not any(c.fatal and not c.passed for c in [warn])
