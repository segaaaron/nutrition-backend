"""Catalog goals taxonomy collapse — round-3 / 2026-06-04.

Collapses non-canonical `targetGoals[]` tokens to the canonical 5-token enum
(`weight_loss`, `maintain`, `muscle_gain`, `weight_gain`, `health`). Idempotent:
running twice is a no-op.

Inputs
------
- data/meals/nova_meals_catalog.json

Outputs
-------
- data/meals/nova_meals_catalog.json.bak-2026-06-04-v3   (atomic backup)
- data/meals/nova_meals_catalog.json                     (rewritten)
- reports/catalog_goals_collapse_2026_06_04.json         (per-record diff log)

Owner-ruled scope (CLAUDE.md GR#3): enum stays at 5 tokens. Any tail token
not listed in COLLAPSE_MAP is reported under `unmapped_tail` for owner triage
and left unchanged in the record (no silent drop).
"""
from __future__ import annotations

import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "data" / "meals" / "nova_meals_catalog.json"
BACKUP = ROOT / "data" / "meals" / "nova_meals_catalog.json.bak-2026-06-04-v3"
REPORT = ROOT / "reports" / "catalog_goals_collapse_2026_06_04.json"

CANONICAL_GOALS: frozenset[str] = frozenset(
    {"weight_loss", "maintain", "muscle_gain", "weight_gain", "health"}
)

# Owner-approved collapse map (round-3, 2026-06-04).
COLLAPSE_MAP: dict[str, str] = {
    # muscle_gain bucket
    "build_muscle": "muscle_gain",
    "muscle_building": "muscle_gain",
    "muscle_hypertrophy": "muscle_gain",
    "muscle_recovery": "muscle_gain",
    "muscle_preservation": "muscle_gain",
    "post_workout_recovery": "muscle_gain",
    # maintain bucket
    "maintain_weight": "maintain",
    "weight_maintenance": "maintain",
    "weight_management": "maintain",
    "weight_preservation": "maintain",
    # weight_gain bucket
    "gain_weight": "weight_gain",
    # health bucket
    "general_health": "health",
    "general_wellness": "health",
    "health_maintenance": "health",
    "wellness": "health",
}


def main() -> int:
    records = json.loads(CATALOG.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise SystemExit("catalog must be a JSON array")

    # Atomic backup (skip if already exists — idempotent).
    if not BACKUP.exists():
        shutil.copy2(CATALOG, BACKUP)

    collapse_counts: Counter[str] = Counter()
    unmapped_tail: Counter[str] = Counter()
    per_record: list[dict] = []
    records_modified = 0
    records_with_empty_after = 0

    for rec in records:
        rid = rec.get("id", "<unknown>")
        mc = rec.setdefault("matchingCriteria", {})
        original = list(mc.get("targetGoals") or [])
        if not original:
            # Pre-existing empty goals — leave alone; flag.
            continue

        collapsed: list[str] = []
        diffs: list[tuple[str, str]] = []
        for tok in original:
            if tok in CANONICAL_GOALS:
                collapsed.append(tok)
            elif tok in COLLAPSE_MAP:
                tgt = COLLAPSE_MAP[tok]
                collapsed.append(tgt)
                collapse_counts[f"{tok}->{tgt}"] += 1
                diffs.append((tok, tgt))
            else:
                # Unmapped tail — keep unchanged + report.
                collapsed.append(tok)
                unmapped_tail[tok] += 1
                diffs.append((tok, "<UNMAPPED>"))

        # Dedup while preserving deterministic order (sorted).
        deduped = sorted(set(collapsed))

        if deduped != original:
            records_modified += 1
            per_record.append(
                {"id": rid, "before": original, "after": deduped, "diffs": diffs}
            )
            mc["targetGoals"] = deduped

        if not deduped:
            records_with_empty_after += 1

    CATALOG.write_text(
        json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "catalog_path": str(CATALOG),
        "backup_path": str(BACKUP),
        "canonical_goals": sorted(CANONICAL_GOALS),
        "collapse_map": COLLAPSE_MAP,
        "total_records": len(records),
        "records_modified": records_modified,
        "records_empty_after_collapse": records_with_empty_after,
        "collapse_counts": dict(collapse_counts),
        "tokens_collapsed_total": sum(collapse_counts.values()),
        "unmapped_tail": dict(unmapped_tail),
        "per_record_diffs": per_record,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"records_modified={records_modified}")
    print(f"tokens_collapsed_total={sum(collapse_counts.values())}")
    print(f"collapse_counts={dict(collapse_counts)}")
    print(f"unmapped_tail={dict(unmapped_tail)}")
    print(f"records_empty_after_collapse={records_with_empty_after}")
    print(f"report -> {REPORT}")
    print(f"backup -> {BACKUP}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
