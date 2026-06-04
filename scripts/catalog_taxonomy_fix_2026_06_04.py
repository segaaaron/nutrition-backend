"""Catalog taxonomy fix (2026-06-04).

Fixes two QA-blocker classes in `data/meals/nova_meals_catalog.json`:

  Bug 1 — condition_vocab (832 fails): allergen tokens leaked into
          recommendedForConditions / contraindicatedConditions. Move them to
          allergens[] and remove from condition arrays. Also normalise any
          remaining condition synonyms (ES/legacy → EN canonical) so we do not
          drop legitimate medical tokens silently.

  Bug 2 — allergen_completeness (760 fails): ingredient lexicon detects an
          allergen (e.g. 'leche' → 'dairy') that is not in allergens[].
          Re-run the lexicon detector and union the result into allergens[].

This script touches ONLY taxonomy / labelling fields:
    matchingCriteria.allergens
    matchingCriteria.recommendedForConditions
    matchingCriteria.contraindicatedConditions

It does NOT modify any nutritional value, ingredient, instruction, name, or id.

Outputs:
    data/meals/nova_meals_catalog.json                (in-place rewrite)
    data/meals/nova_meals_catalog.json.bak-2026-06-04 (atomic backup)
    reports/catalog_taxonomy_fix_2026_06_04.json      (per-record diff log)

Total records must remain 1997.
"""
from __future__ import annotations

import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Reuse the single source of truth from the audit module.
from audit_catalog import (  # type: ignore
    ALLERGEN_ENUM,
    ALLERGEN_SYNONYMS,
    CANONICAL_CONDITIONS,
    CONDITION_SYNONYMS,
    _collect_expected_allergens,
)

ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = ROOT / "data" / "meals" / "nova_meals_catalog.json"
BACKUP_PATH = ROOT / "data" / "meals" / "nova_meals_catalog.json.bak-2026-06-04"
REPORT_PATH = ROOT / "reports" / "catalog_taxonomy_fix_2026_06_04.json"

CONDITION_FIELDS = ("recommendedForConditions", "contraindicatedConditions")

# Round-3 extension: tokens like 'egg_allergy', 'soy_allergy', 'gluten_intolerance'
# are allergen statements masquerading as conditions. Route them into
# allergens[] using the canonical 14-item enum.
ALLERGY_SUFFIX_MAP: dict[str, str] = {
    "egg_allergy": "egg",
    "soy_allergy": "soy",
    "fish_allergy": "fish",
    "peanut_allergy": "peanuts",
    "peanuts_allergy": "peanuts",
    "dairy_allergy": "dairy",
    "milk_allergy": "dairy",
    "shellfish_allergy": "shellfish",
    "tree_nuts_allergy": "tree_nuts",
    "nut_allergy": "tree_nuts",
    "sesame_allergy": "sesame",
    "gluten_intolerance": "gluten",
    "wheat_allergy": "gluten",
    "lactose_allergy": "dairy",
}


def _dedup_preserve(seq: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def fix_record(rec: dict[str, Any]) -> dict[str, Any]:
    """Apply Bug 1 + Bug 2 fixes. Returns diff dict (empty if no change)."""
    mc = rec.setdefault("matchingCriteria", {})
    allergens_raw = list(mc.get("allergens") or [])
    allergens = [ALLERGEN_SYNONYMS.get(a, a) for a in allergens_raw]
    allergens = [a for a in allergens if a in ALLERGEN_ENUM]

    diff: dict[str, Any] = {
        "id": rec.get("id"),
        "removed_from_conditions": {},
        "added_to_allergens": [],
        "condition_synonyms_collapsed": {},
        "unknown_conditions_kept": {},   # NOT silently dropped — flagged for owner
    }

    # ---- Bug 1: clean condition arrays ----
    for fld in CONDITION_FIELDS:
        original = list(mc.get(fld) or [])
        removed: list[str] = []
        cleaned: list[str] = []
        unknown: list[str] = []
        collapsed: dict[str, str] = {}
        for tok in original:
            # *_allergy / *_intolerance suffix → route to allergens[]
            if tok in ALLERGY_SUFFIX_MAP:
                removed.append(tok)
                allergens.append(ALLERGY_SUFFIX_MAP[tok])
                continue
            # allergen leak?
            allergen_norm = ALLERGEN_SYNONYMS.get(tok, tok)
            if tok in ALLERGEN_ENUM or tok in ALLERGEN_SYNONYMS or allergen_norm in ALLERGEN_ENUM:
                removed.append(tok)
                if allergen_norm in ALLERGEN_ENUM:
                    allergens.append(allergen_norm)
                continue
            # canonical?
            if tok in CANONICAL_CONDITIONS:
                cleaned.append(tok)
                continue
            # synonym?
            canon = CONDITION_SYNONYMS.get(tok)
            if canon and canon in CANONICAL_CONDITIONS:
                if canon != tok:
                    collapsed[tok] = canon
                cleaned.append(canon)
                continue
            # unknown — keep it but flag for owner triage (do NOT silently drop)
            unknown.append(tok)
            cleaned.append(tok)
        cleaned = _dedup_preserve(cleaned)
        if cleaned != original:
            mc[fld] = cleaned
        if removed:
            diff["removed_from_conditions"][fld] = removed
        if collapsed:
            diff["condition_synonyms_collapsed"][fld] = collapsed
        if unknown:
            diff["unknown_conditions_kept"][fld] = unknown

    # ---- Bug 2: backfill allergens from ingredient lexicon ----
    ings = (rec.get("execution") or {}).get("ingredients") or []
    expected = _collect_expected_allergens(ings)
    pre_set = set(allergens)
    missing = expected - pre_set
    if missing:
        allergens.extend(sorted(missing))
        diff["added_to_allergens"].extend(sorted(missing))

    # Also record allergens we added from condition leaks (delta vs original).
    final_allergens = sorted(set(allergens))
    pre_original = sorted({ALLERGEN_SYNONYMS.get(a, a) for a in allergens_raw if ALLERGEN_SYNONYMS.get(a, a) in ALLERGEN_ENUM})
    leak_added = sorted(set(final_allergens) - set(pre_original) - set(missing))
    if leak_added:
        diff["added_to_allergens"].extend(leak_added)
    diff["added_to_allergens"] = sorted(set(diff["added_to_allergens"]))

    mc["allergens"] = final_allergens

    # Empty diff if nothing changed.
    if (not diff["removed_from_conditions"]
            and not diff["added_to_allergens"]
            and not diff["condition_synonyms_collapsed"]
            and not diff["unknown_conditions_kept"]):
        return {}
    return diff


def main() -> int:
    if not CATALOG_PATH.exists():
        print(f"catalog not found: {CATALOG_PATH}")
        return 2

    records = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        print("catalog must be a JSON array")
        return 2
    total_before = len(records)

    # Atomic backup before mutating (idempotent: skip if backup already exists).
    if not BACKUP_PATH.exists():
        shutil.copy2(CATALOG_PATH, BACKUP_PATH)
    else:
        print(f"backup already exists at {BACKUP_PATH}, skipping copy (idempotent re-run)")

    diffs: list[dict[str, Any]] = []
    counter: Counter[str] = Counter()
    unknown_token_freq: Counter[str] = Counter()

    for rec in records:
        diff = fix_record(rec)
        if diff:
            diffs.append(diff)
            if diff["removed_from_conditions"]:
                counter["records_with_allergen_leak"] += 1
                for fld, toks in diff["removed_from_conditions"].items():
                    counter[f"leaks_removed_{fld}"] += len(toks)
            if diff["added_to_allergens"]:
                counter["records_with_allergens_added"] += 1
                counter["allergens_added_total"] += len(diff["added_to_allergens"])
            if diff["condition_synonyms_collapsed"]:
                counter["records_with_synonyms_collapsed"] += 1
            if diff["unknown_conditions_kept"]:
                counter["records_with_unknown_conditions"] += 1
                for fld, toks in diff["unknown_conditions_kept"].items():
                    for t in toks:
                        unknown_token_freq[t] += 1

    total_after = len(records)
    assert total_before == total_after, (
        f"record count drifted: {total_before} → {total_after}"
    )

    # Atomic write.
    tmp = CATALOG_PATH.with_suffix(CATALOG_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(CATALOG_PATH)

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(
            {
                "ran_at": datetime.now(timezone.utc).isoformat(),
                "catalog_path": str(CATALOG_PATH),
                "backup_path": str(BACKUP_PATH),
                "total_records_before": total_before,
                "total_records_after": total_after,
                "summary": dict(counter),
                "unknown_condition_tokens_kept_for_owner_triage": dict(
                    sorted(unknown_token_freq.items(), key=lambda kv: -kv[1])
                ),
                "diffs": diffs,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"catalog rewritten: {CATALOG_PATH}")
    print(f"backup:            {BACKUP_PATH}")
    print(f"report:            {REPORT_PATH}")
    print(f"records: {total_before} → {total_after} (unchanged)")
    print(f"summary: {dict(counter)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
