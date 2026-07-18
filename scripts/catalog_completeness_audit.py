"""Catalog completeness audit — boot gate + CI gate.

Checks NULL ratio on CRITICAL_COLUMNS in the recipes + recipe_components
tables. Three exit codes:

  0 — clean (all ratios within soft threshold)
  1 — CI gate breached (hard threshold exceeded → block deploy)
  3 — boot gate breached (soft threshold exceeded → warn at startup)

Usage:
    python3 scripts/catalog_completeness_audit.py
    python3 scripts/catalog_completeness_audit.py --json   # machine-readable
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal

# Columns the R6 fail-closed Layer 1 filters depend on.
# Changing this set narrows/expands the boot-gate surface — update the
# locked test in tests/unit/catalog/test_audit_critical_columns_nonempty.py
# and open an ADR before modifying.
#
# potassium_mg: demoted to INFO tier 2026-06-03 (CKD onboarding blocked
# during closed-beta). Re-promote before enabling CKD onboarding.
CRITICAL_COLUMNS: list[str] = [
    "sugar_g",
    "sodium_mg",
    "sat_fat_g",
    "protein_g",
    "fiber_g",
]

_SOFT_THRESHOLD_DEFAULT = Decimal("0.05")   # 5%  → boot warn
_HARD_THRESHOLD_DEFAULT = Decimal("0.10")   # 10% → CI block / boot refuse


@dataclass
class ColumnAudit:
    """Per-column NULL audit result."""

    column: str
    null_count: int
    total: int

    @property
    def ratio(self) -> Decimal:
        """NULL ratio, quantised to 4 dp. Returns 0 on empty table."""
        if self.total == 0:
            return Decimal("0")
        raw = Decimal(self.null_count) / Decimal(self.total)
        return raw.quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN)


def classify(
    audits: list[ColumnAudit],
    *,
    soft_threshold: Decimal = _SOFT_THRESHOLD_DEFAULT,
    hard_threshold: Decimal = _HARD_THRESHOLD_DEFAULT,
) -> tuple[bool, bool]:
    """Return (soft_breached, hard_breached).

    Strict inequality: a ratio exactly at the threshold is NOT a breach.
    """
    soft = any(a.ratio > soft_threshold for a in audits)
    hard = any(a.ratio > hard_threshold for a in audits)
    return soft, hard


async def _audit_db(database_url: str) -> list[ColumnAudit]:
    """Run NULL audit against the live DB using asyncpg — the project's only DB
    driver (2026-07-18: was psycopg2, which is not a dependency; every boot logged
    'DB audit failed: No module named psycopg2')."""
    import asyncpg  # noqa: PLC0415

    # SQLAlchemy asyncpg URL → plain DSN that asyncpg.connect accepts.
    url = database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(url)
    try:
        results: list[ColumnAudit] = []
        for col in CRITICAL_COLUMNS:
            row = await conn.fetchrow(
                f"SELECT COUNT(*) FILTER (WHERE {col} IS NULL) AS nulls, "  # noqa: S608
                "COUNT(*) AS total FROM recipes"
            )
            results.append(
                ColumnAudit(column=col, null_count=row["nulls"], total=row["total"])
            )
        return results
    finally:
        await conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Catalog NULL completeness audit")
    parser.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    parser.add_argument(
        "--soft", type=float, default=float(_SOFT_THRESHOLD_DEFAULT), help="Soft threshold"
    )
    parser.add_argument(
        "--hard", type=float, default=float(_HARD_THRESHOLD_DEFAULT), help="Hard threshold"
    )
    parser.add_argument(
        "--boot-guard", action="store_true", help="Boot guard mode (entrypoint label, no-op)"
    )
    args = parser.parse_args(argv)

    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        return 2

    try:
        audits = asyncio.run(_audit_db(db_url))
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: DB audit failed: {exc}", file=sys.stderr)
        return 2

    soft_t = Decimal(str(args.soft))
    hard_t = Decimal(str(args.hard))
    soft_breached, hard_breached = classify(audits, soft_threshold=soft_t, hard_threshold=hard_t)

    max_ratio = max((a.ratio for a in audits), default=Decimal("0"))

    if args.json:
        print(
            json.dumps(
                {
                    "cols": len(audits),
                    "max_null_ratio": str(max_ratio),
                    "soft_breached": soft_breached,
                    "hard_breached": hard_breached,
                    "columns": [
                        {"col": a.column, "null_count": a.null_count, "ratio": str(a.ratio)}
                        for a in audits
                    ],
                }
            )
        )
    else:
        print(f"cols={len(audits)} max_null_ratio={max_ratio}")
        for a in audits:
            flag = "⚠️" if a.ratio > soft_t else "✓"
            print(f"  {flag} {a.column}: {a.null_count}/{a.total} ({a.ratio})")

    if hard_breached:
        return 1   # CI block
    if soft_breached:
        return 3   # boot warn
    return 0


if __name__ == "__main__":
    sys.exit(main())
