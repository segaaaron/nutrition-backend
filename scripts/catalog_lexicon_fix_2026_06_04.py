"""Catalog allergen lexicon fix (2026-06-04, round 4).

QA found two safety-critical lexicon defects:

  BLOCK-1 (FALSE-NEGATIVE, NN Pillar #2 violation):
      Ingredient-→-allergen lexicon did not detect dairy in dairy-derived
      protein ingredients (whey, caseína, caseinato, suero de leche,
      lactosuero, leche en polvo, ...). A dairy-allergic user could have
      received "proteína whey" without the dairy allergen flag.

  P1-2 (FALSE-POSITIVES):
      The substring match for "leche" / "milk" wrongly fired on plant milks
      (leche de almendra/coco/soja/...). 11 known records were
      mis-tagged `dairy` when no dairy was present.

Both are addressed by editing the lexicon in `scripts/audit_catalog.py`:
  - Removed ambiguous tokens "leche", "milk", "suero" from the flat
    INGREDIENT_ALLERGEN_LEXICON.
  - Added dairy-derived markers: whey, caseina(to), nata, lactosuero,
    buttermilk, casein, etc.
  - Added a phrase-aware pass in `_collect_expected_allergens` with a
    negative lookahead that suppresses "leche/milk" hits when surrounded
    by plant qualifiers (almendra, coco, soja, avena, ...).

This script re-runs the (now corrected) detector against the full catalog
and rewrites `matchingCriteria.allergens` per record. It is idempotent.

POLICY for this run:
  - For ALL allergens other than `dairy`: declared ∪ detected (additive,
    never strip — preserves manual annotations).
  - For `dairy` SPECIFICALLY: trust the new detector. If the new detector
    does NOT see dairy AND the record currently declares dairy, REMOVE it
    (false-positive cleanup from prior round-3 backfill). Every removal
    is logged explicitly.

Outputs:
  data/meals/nova_meals_catalog.json                 (in-place)
  data/meals/nova_meals_catalog.json.bak-2026-06-04-v4   (atomic, guarded)
  reports/catalog_lexicon_fix_2026_06_04.json        (per-record diff log)

Total records MUST remain 1997.
"""
from __future__ import annotations

import json
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Reuse single-source-of-truth lexicon + detector from the audit module.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_catalog import _collect_expected_allergens  # type: ignore  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "data" / "meals" / "nova_meals_catalog.json"
BACKUP = ROOT / "data" / "meals" / "nova_meals_catalog.json.bak-2026-06-04-v4"
REPORT = ROOT / "reports" / "catalog_lexicon_fix_2026_06_04.json"


def main() -> int:
    if not CATALOG.exists():
        print(f"ERROR: catalog not found at {CATALOG}", file=sys.stderr)
        return 1

    # Atomic backup, guarded — never overwrite a previous backup.
    if BACKUP.exists():
        print(f"INFO: backup already exists at {BACKUP}; skipping copy.")
    else:
        shutil.copy2(CATALOG, BACKUP)
        print(f"INFO: backup written to {BACKUP}")

    raw = json.loads(CATALOG.read_text(encoding="utf-8"))
    records: list[dict[str, Any]]
    if isinstance(raw, list):
        records = raw
        wrapper_key = None
    elif isinstance(raw, dict):
        for k in ("meals", "records", "data"):
            if isinstance(raw.get(k), list):
                wrapper_key = k
                records = raw[k]
                break
        else:
            print("ERROR: unknown catalog wrapper", file=sys.stderr)
            return 2
    else:
        print("ERROR: catalog is neither list nor dict", file=sys.stderr)
        return 2

    diffs: list[dict[str, Any]] = []
    counters: Counter[str] = Counter()
    counters["total_records"] = len(records)

    for rec in records:
        rid = rec.get("id", "<unknown>")
        ings = rec.get("execution", {}).get("ingredients", []) or []
        declared = set(rec.get("matchingCriteria", {}).get("allergens", []) or [])
        detected = _collect_expected_allergens(ings)

        # Additive union for non-dairy allergens.
        new_set = set(declared) | (detected - {"dairy"})

        # Dairy: trust new detector strictly.
        if "dairy" in detected:
            new_set.add("dairy")
        else:
            new_set.discard("dairy")  # FP cleanup if previously declared

        added = sorted(new_set - declared)
        removed = sorted(declared - new_set)

        if added or removed:
            rec.setdefault("matchingCriteria", {})["allergens"] = sorted(new_set)
            diffs.append({
                "id": rid,
                "before": sorted(declared),
                "after": sorted(new_set),
                "added": added,
                "removed": removed,
                "dairy_added": "dairy" in added,
                "dairy_removed": "dairy" in removed,
            })
            counters["records_changed"] += 1
            if "dairy" in added:
                counters["dairy_added"] += 1
            if "dairy" in removed:
                counters["dairy_removed_false_positive"] += 1
            for a in added:
                counters[f"added::{a}"] += 1
            for a in removed:
                counters[f"removed::{a}"] += 1

    # Write back catalog.
    payload: Any
    if wrapper_key is None:
        payload = records
    else:
        raw[wrapper_key] = records
        payload = raw

    tmp = CATALOG.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CATALOG)

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "catalog": str(CATALOG.relative_to(ROOT)),
                "backup": str(BACKUP.relative_to(ROOT)),
                "counters": dict(counters),
                "diffs": diffs,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"INFO: report written to {REPORT}")
    print(f"INFO: counters = {dict(counters)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
