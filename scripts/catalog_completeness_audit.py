"""Catalog completeness audit — NULL ratio for critical nutrient columns.

R6 fail-closed policy (2026-06-03): Layer 1 eligibility excludes recipes
whose nutrition-critical columns are NULL. This script measures the cost of
that policy in terms of catalog coverage and signals when backfill is
required to keep the candidate pool healthy.

Usage
-----

    make catalog-audit              # CLI wrapper, fails on >5% NULL
    python -m scripts.catalog_completeness_audit
    python -m scripts.catalog_completeness_audit --threshold 0.10 --json

Exit codes
----------
    0  all critical columns within threshold
    1  at least one critical column exceeds soft threshold (CI gate)
    2  DB connection / SQL failure
    3  at least one critical column exceeds hard threshold (boot guard)

Soft vs hard thresholds (sprint 3 D3)
-------------------------------------
Soft (`--threshold`, default 0.05): CI gate. PRs that push the NULL
ratio above 5% on any critical column fail the build. Used as the
GitHub Actions enforcement step.

Hard (`--fail-hard-threshold`, default 0.10): boot guard. Container
entrypoint runs the audit in `--fail-hard-threshold-only` mode and
refuses to hand off to uvicorn if any critical column exceeds 10%.
Fail-closed catastrophe prevention: a broken catalogue ingest must
not boot a production API that would silently filter every recipe
for affected users.

Output
------
Tabular report on stdout (or JSON with `--json`):

    column            null_count    total    ratio    status
    sugar_g                  12     1820   0.0066    OK
    sodium_mg               287     1820   0.1577    BREACH
    ...

Side effects
------------
Updates the `catalog_null_ratio{column=...}` Prometheus Gauge so the metric
is observable from `/metrics` after the script runs (useful when invoked
from a cron — see docs/ops/CATALOG_AUDIT.md for the recommended schedule).

NOVA scope: catalogue hygiene, not nutrition guidance.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import text

from app.core.db import dispose_engine, session_scope
from app.core.metrics import CATALOG_NULL_RATIO

# Critical columns audited. Order matters: shown in the report top-down.
# `sugar_g`, `sodium_mg`, `sat_fat_g`, `protein_g`, `fiber_g` directly drive
# R6 fail-closed filters in `app/plan/application/layer1_eligibility.py` for
# diabetes_t2 / hypertension / hypercholesterolemia / cardio.
#
# `potassium_mg` is INFORMATIONAL-only (CKD gate). CKD onboarding is gated
# off during closed-beta per QA condition, so a high NULL ratio on potassium
# does NOT block boot. Tracked in `_INFO_COLUMNS` for telemetry + future
# backfill scheduling. Move to `CRITICAL_COLUMNS` before CKD onboarding flip.
CRITICAL_COLUMNS: tuple[str, ...] = (
    "sugar_g",
    "sodium_mg",
    "sat_fat_g",
    "protein_g",
    "fiber_g",
)

_INFO_COLUMNS: tuple[str, ...] = (
    "potassium_mg",
)

_DEFAULT_THRESHOLD: Decimal = Decimal("0.05")
_DEFAULT_HARD_THRESHOLD: Decimal = Decimal("0.10")


def classify(
    audits: list["ColumnAudit"],
    *,
    soft_threshold: Decimal,
    hard_threshold: Decimal,
) -> tuple[bool, bool]:
    """Pure classifier — returns (soft_breached, hard_breached).

    Extracted so unit tests can exercise the threshold semantics on
    synthetic ColumnAudit fixtures without spinning up Postgres.
    Hard breach implies soft breach (10% > 5%) but we keep both flags
    explicit so the CI gate (exit 1) and boot guard (exit 3) are
    distinguishable in the wrapper logic.
    """
    critical = [a for a in audits if a.column in CRITICAL_COLUMNS]
    soft = any(a.ratio > soft_threshold for a in critical)
    hard = any(a.ratio > hard_threshold for a in critical)
    return soft, hard


@dataclass(frozen=True, slots=True)
class ColumnAudit:
    column: str
    null_count: int
    total: int

    @property
    def ratio(self) -> Decimal:
        if self.total == 0:
            return Decimal("0")
        return (Decimal(self.null_count) / Decimal(self.total)).quantize(Decimal("0.0001"))


async def _audit(threshold: Decimal) -> tuple[list[ColumnAudit], bool]:
    """Returns (audits, breached).

    Audits CRITICAL_COLUMNS (breach affects boot/CI exit codes) AND
    _INFO_COLUMNS (telemetry-only, never sets `breached`). Closes session
    via context manager.
    """
    audits: list[ColumnAudit] = []
    breached = False
    async with session_scope() as session:
        for col in (*CRITICAL_COLUMNS, *_INFO_COLUMNS):
            # S608 noqa: identifier `col` is selected from closed module-
            # level allowlists. No user input reaches the SQL string.
            # Identifiers cannot be parameter-bound in SQL.
            query = (
                f"SELECT COUNT(*) FILTER (WHERE {col} IS NULL) AS nulls, "  # noqa: S608
                "COUNT(*) AS total FROM recipes"
            )
            row = (await session.execute(text(query))).first()
            nulls = int(row[0]) if row and row[0] is not None else 0
            total = int(row[1]) if row and row[1] is not None else 0
            audit = ColumnAudit(column=col, null_count=nulls, total=total)
            audits.append(audit)
            CATALOG_NULL_RATIO.labels(column=col).set(float(audit.ratio))
            if col in CRITICAL_COLUMNS and audit.ratio > threshold:
                breached = True
    return audits, breached


def _format_table(audits: list[ColumnAudit], threshold: Decimal) -> str:
    header = f"{'column':<18}{'null_count':>12}{'total':>10}{'ratio':>10}    status"
    lines = [header, "-" * len(header)]
    for a in audits:
        if a.column in _INFO_COLUMNS:
            status = "INFO"
        elif a.ratio > threshold:
            status = "BREACH"
        else:
            status = "OK"
        lines.append(
            f"{a.column:<18}{a.null_count:>12}{a.total:>10}{str(a.ratio):>10}    {status}"
        )
    return "\n".join(lines)


def _format_json(audits: list[ColumnAudit], threshold: Decimal) -> str:
    return json.dumps(
        {
            "threshold": str(threshold),
            "rows": [
                {
                    "column": a.column,
                    "null_count": a.null_count,
                    "total": a.total,
                    "ratio": str(a.ratio),
                    "tier": "info" if a.column in _INFO_COLUMNS else "critical",
                    "breach": a.column in CRITICAL_COLUMNS and a.ratio > threshold,
                }
                for a in audits
            ],
        },
        indent=2,
    )


async def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--threshold",
        type=Decimal,
        default=_DEFAULT_THRESHOLD,
        help="Soft NULL ratio above which a column is flagged (default 0.05).",
    )
    parser.add_argument(
        "--fail-hard-threshold",
        type=Decimal,
        default=_DEFAULT_HARD_THRESHOLD,
        help=(
            "Hard NULL ratio. Exit code 3 when exceeded. Used by the "
            "container entrypoint as a fail-closed boot guard (default 0.10)."
        ),
    )
    parser.add_argument(
        "--boot-guard",
        action="store_true",
        help=(
            "Only fail on hard threshold breach. Used at container "
            "boot to refuse a catastrophic catalogue state but tolerate "
            "non-catastrophic drift that would otherwise block deploys."
        ),
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of table.")
    args = parser.parse_args()

    try:
        audits, _ = await _audit(args.threshold)
    except Exception as exc:  # noqa: BLE001 — top-level CLI handler
        print(f"audit_failed: {exc}", file=sys.stderr)
        return 2
    finally:
        await dispose_engine()

    soft_breached, hard_breached = classify(
        audits,
        soft_threshold=args.threshold,
        hard_threshold=args.fail_hard_threshold,
    )

    if args.json:
        out = _format_json(audits, args.threshold)
    else:
        out = _format_table(audits, args.threshold)
    print(out)

    if args.boot_guard:
        # Boot guard mode: only block on catastrophic breach.
        return 3 if hard_breached else 0
    if hard_breached:
        return 3
    return 1 if soft_breached else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
