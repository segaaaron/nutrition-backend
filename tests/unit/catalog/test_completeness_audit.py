"""Sprint 3 D3 — Catalog completeness audit classifier tests.

Exercises the pure `classify` function on synthetic ColumnAudit fixtures.
The live DB-bound `_audit` is covered by a separate integration test
that needs Postgres; this module locks down the threshold semantics
that drive CI gate (exit 1) vs boot guard (exit 3).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from scripts.catalog_completeness_audit import (
    CRITICAL_COLUMNS,
    ColumnAudit,
    classify,
)


def _audit(col: str, nulls: int, total: int = 1000) -> ColumnAudit:
    return ColumnAudit(column=col, null_count=nulls, total=total)


def test_all_clean_no_breach():
    audits = [_audit(c, nulls=10) for c in CRITICAL_COLUMNS]  # 1.0% each
    soft, hard = classify(
        audits,
        soft_threshold=Decimal("0.05"),
        hard_threshold=Decimal("0.10"),
    )
    assert soft is False
    assert hard is False


def test_soft_breach_no_hard_breach():
    """6% NULL ratio: tripped soft (5%) but below hard (10%)."""
    audits = [_audit("sugar_g", nulls=60)] + [
        _audit(c, nulls=10) for c in CRITICAL_COLUMNS if c != "sugar_g"
    ]
    soft, hard = classify(
        audits,
        soft_threshold=Decimal("0.05"),
        hard_threshold=Decimal("0.10"),
    )
    assert soft is True
    assert hard is False


def test_hard_breach_blocks_boot():
    """15% NULL ratio: above hard threshold → boot guard must refuse."""
    audits = [_audit("sodium_mg", nulls=150)] + [
        _audit(c, nulls=10) for c in CRITICAL_COLUMNS if c != "sodium_mg"
    ]
    soft, hard = classify(
        audits,
        soft_threshold=Decimal("0.05"),
        hard_threshold=Decimal("0.10"),
    )
    assert soft is True
    assert hard is True


def test_threshold_is_strict_inequality():
    """Exactly at threshold is OK; only `>` trips the breach.

    Semantic anchor: a column with exactly the threshold ratio is
    on the boundary, not over it. Avoids spurious CI failures when
    operators tune the threshold to match observed steady-state."""
    # Exactly 5.00% — boundary, not breach.
    audits = [_audit("sugar_g", nulls=50, total=1000)] + [
        _audit(c, nulls=10) for c in CRITICAL_COLUMNS if c != "sugar_g"
    ]
    soft, hard = classify(
        audits,
        soft_threshold=Decimal("0.05"),
        hard_threshold=Decimal("0.10"),
    )
    assert soft is False
    assert hard is False


def test_ratio_handles_empty_table():
    """Empty recipes table: ratio is 0/0 → 0 (no division-by-zero)."""
    a = _audit("sugar_g", nulls=0, total=0)
    assert a.ratio == Decimal("0")


def test_critical_columns_cover_r6_fail_closed_set():
    """Lock down the columns the boot guard protects. Adding/removing
    any of these changes the fail-closed surface of Layer 1 and MUST
    go through an ADR + this test update.

    `potassium_mg` was demoted to INFO tier 2026-06-03 — CKD onboarding
    blocked during closed-beta, so potassium NULL ratio is tracked for
    telemetry only and does not block boot. Re-promote to CRITICAL
    before flipping CKD onboarding on.
    """
    assert set(CRITICAL_COLUMNS) == {
        "sugar_g",
        "sodium_mg",
        "sat_fat_g",
        "protein_g",
        "fiber_g",
    }


@pytest.mark.parametrize(
    "nulls,total,expected",
    [
        (50, 1000, Decimal("0.0500")),
        (100, 1000, Decimal("0.1000")),
        (101, 1000, Decimal("0.1010")),
        (1, 3, Decimal("0.3333")),
    ],
)
def test_ratio_quantisation(nulls: int, total: int, expected: Decimal):
    assert _audit("sugar_g", nulls, total).ratio == expected
