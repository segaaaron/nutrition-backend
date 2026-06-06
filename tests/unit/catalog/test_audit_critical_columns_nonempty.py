"""Guard against silent boot-gate degradation (QA finding R4, 2026-06-06).

Background
----------
After the ``catalog_completeness_audit`` quiet-success refactor, a boot
emits a single summary line on the happy path. If somebody ever empties
``CRITICAL_COLUMNS`` (e.g. during a sloppy refactor), ``classify`` would
trivially return ``False, False``, the script would print
``cols=0 max_null_ratio=0`` and the entrypoint would happily start
uvicorn against a catalogue that nobody is auditing.

This test fences the invariant: the critical-column allowlist MUST
contain the five columns the R6 fail-closed Layer 1 filters depend on.
Reducing the set requires updating this test, forcing an ADR-style
review of the protected surface.
"""

from __future__ import annotations

from scripts.catalog_completeness_audit import CRITICAL_COLUMNS


def test_critical_columns_nonempty_protects_boot_gate() -> None:
    assert len(CRITICAL_COLUMNS) >= 5, (
        "CRITICAL_COLUMNS shrank — boot guard would silently pass on a "
        "catalogue with stealth NULLs. Restore the allowlist or open an "
        "ADR explaining why the fail-closed surface narrowed."
    )


def test_critical_columns_locks_r6_set() -> None:
    """Lock the exact set. Adding a column requires updating both this
    test and the R6 fail-closed Layer 1 filters."""
    assert set(CRITICAL_COLUMNS) == {
        "sugar_g",
        "sodium_mg",
        "sat_fat_g",
        "protein_g",
        "fiber_g",
    }
