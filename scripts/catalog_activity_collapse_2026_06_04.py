"""Catalog activity-levels collapse — round-3 / 2026-06-04.

Collapses non-canonical `suitableForActivity[]` tokens to the canonical 5-token
enum (`sedentary`, `lightly_active`, `moderately_active`, `very_active`,
`extra_active`). Idempotent: running twice is a no-op (backup is guarded by
`.exists()` so it cannot be overwritten).

Source of truth for ACTIVITY_LEVELS_5: `app.shared.domain.vocabularies`.

Owner-approved collapse map (CLAUDE.md GR#3, 2026-06-04):
- `moderate` → `moderately_active`
- `active`   → `very_active`

Already-canonical tokens (`sedentary`, `lightly_active`, `very_active`,
`extra_active`, `moderately_active`) are left untouched.

Inputs
------
- data/meals/nova_meals_catalog.json

Outputs
-------
- data/meals/nova_meals_catalog.json.bak-2026-06-04-v5   (atomic backup, idempotent)
- data/meals/nova_meals_catalog.json                     (rewritten)
- reports/catalog_activity_collapse_2026_06_04.json      (per-record diff log)
"""
from __future__ import annotations

import json
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.shared.domain.vocabularies import ACTIVITY_LEVELS_5  # noqa: E402

CATALOG = ROOT / "data" / "meals" / "nova_meals_catalog.json"
BACKUP = ROOT / "data" / "meals" / "nova_meals_catalog.json.bak-2026-06-04-v5"
REPORT = ROOT / "reports" / "catalog_activity_collapse_2026_06_04.json"

CANONICAL_ACTIVITY_LEVELS: frozenset[str] = frozenset(ACTIVITY_LEVELS_5)

# Owner-approved collapse map (round-3, 2026-06-04).
COLLAPSE_MAP: dict[str, str] = {
    "moderate": "moderately_active",
    "active": "very_active",
}


def main() -> int:
    records = json.loads(CATALOG.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise SystemExit("catalog must be a JSON array")

    # Atomic backup (skip if already exists — idempotent).
    if not BACKUP.exists():
        shutil.copy2(CATALOG, BACKUP)
    else:
        print(f"backup already exists at {BACKUP}, skipping copy (idempotent re-run)")

    collapse_counts: Counter[str] = Counter()
    unmapped_tail: Counter[str] = Counter()
    per_record: list[dict] = []
    records_modified = 0
    records_with_empty_after = 0

    for rec in records:
        rid = rec.get("id", "<unknown>")
        mc = rec.setdefault("matchingCriteria", {})
        original = list(mc.get("suitableForActivity") or [])
        if not original:
            continue

        collapsed: list[str] = []
        diffs: list[tuple[str, str]] = []
        for tok in original:
            if tok in CANONICAL_ACTIVITY_LEVELS:
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
            mc["suitableForActivity"] = deduped

        if not deduped:
            records_with_empty_after += 1

    # Post-validate: every token in every record MUST be canonical.
    drift: list[tuple[str, str]] = []
    for rec in records:
        rid = rec.get("id", "<unknown>")
        for tok in rec.get("matchingCriteria", {}).get("suitableForActivity") or []:
            if tok not in CANONICAL_ACTIVITY_LEVELS:
                drift.append((rid, tok))
    if drift:
        print(
            f"ABORT: {len(drift)} drift tokens remain after collapse "
            f"(first 5: {drift[:5]})",
            file=sys.stderr,
        )
        return 3

    CATALOG.write_text(
        json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "catalog_path": str(CATALOG),
        "backup_path": str(BACKUP),
        "canonical_activity_levels": sorted(CANONICAL_ACTIVITY_LEVELS),
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
