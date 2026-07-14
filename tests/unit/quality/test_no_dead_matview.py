"""Guard: no application code may query the dead `food_logs_aggregates_daily`
materialised view.

It was created ``WITH NO DATA`` and can never be refreshed under REGLA #3
(no crons), so every SELECT raises "materialized view has not been populated".
Worse, the failing statement — when caught without a rollback — poisons the
request session and cascades ``InFailedSQLTransactionError`` 500s to unrelated
queries. Migration 0029 drops it; this test stops it from being referenced
again in application code (migrations are exempt — they legitimately create /
drop it for reversibility).
"""
from __future__ import annotations

from pathlib import Path

DEAD_OBJECT = "food_logs_aggregates_daily"
APP_DIR = Path(__file__).resolve().parents[3] / "app"


def test_no_app_code_references_dead_matview() -> None:
    offenders: list[str] = []
    for path in APP_DIR.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if DEAD_OBJECT in text:
            for i, line in enumerate(text.splitlines(), start=1):
                if DEAD_OBJECT in line:
                    offenders.append(f"{path}:{i}: {line.strip()}")
    assert not offenders, (
        "Application code must not query the dead matview "
        f"{DEAD_OBJECT!r} (unpopulated, poisons the session on SELECT). "
        "Aggregate directly from food_logs instead:\n" + "\n".join(offenders)
    )
