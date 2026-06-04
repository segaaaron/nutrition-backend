"""Catalog scope cleanup (2026-06-04, v2).

Purpose
-------
Close the residual `condition_vocab` gate failures (644 fails / 34 distinct
non-canonical tokens) left by `catalog_taxonomy_fix_2026_06_04.py`.

CLAUDE.md Golden Rule #3 (project scope) is the driver: NOVA is a nutrition
tracker, not a clinical platform. Medical sub-distinctions (sarcopenia,
metabolic_syndrome, insulin_resistance, menopause, osteoporosis, gastritis,
malnutrition, underweight) and vague wellness tokens (general_health,
general_wellness, digestive_health, cognitive_health, anti_inflammatory)
are OUT of scope and get DROPPED — not silently reclassified.

A small set of muscle/weight-related tokens are actually *goals*, not
conditions, and get MOVED to `matchingCriteria.targetGoals[]`:

    muscle_recovery, muscle_hypertrophy, muscle_building, build_muscle
        → 'muscle_gain' (canonical goal)
    muscle_preservation, post_workout_recovery
        → 'muscle_gain' (best-fit canonical goal)
    weight_gain
        → 'weight_gain' (already canonical)
    weight_management
        → 'maintain' (canonical goal)

One ingestion-error token (`tree_nut_allergy`) is routed to `allergens[]`
as `tree_nuts` — lexicon fix that the prior round's `ALLERGY_SUFFIX_MAP`
missed because it only had the plural form.

Canonical goals enum (from `scripts/seed_recipes.py` line 60, single source
of truth):

    {weight_loss, maintain, muscle_gain, weight_gain, health}

Canonical conditions enum (from `scripts/audit_catalog.py` CANONICAL_CONDITIONS,
25 values).

Outputs
-------
    data/meals/nova_meals_catalog.json                       (in-place rewrite)
    data/meals/nova_meals_catalog.json.bak-2026-06-04-v2     (atomic backup)
    reports/catalog_scope_cleanup_2026_06_04.json            (per-record diff)

Constraints
-----------
- Idempotent: re-running on already-cleaned catalog produces no diff.
- Touches ONLY taxonomy / labelling fields. Macros / ingredients / names
  / instructions / ids untouched.
- Total record count must remain 1997.
"""
from __future__ import annotations

import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from audit_catalog import (  # type: ignore
    ALLERGEN_ENUM,
    ALLERGEN_SYNONYMS,
    CANONICAL_CONDITIONS,
)

ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = ROOT / "data" / "meals" / "nova_meals_catalog.json"
BACKUP_PATH = ROOT / "data" / "meals" / "nova_meals_catalog.json.bak-2026-06-04-v2"
REPORT_PATH = ROOT / "reports" / "catalog_scope_cleanup_2026_06_04.json"

CONDITION_FIELDS = ("recommendedForConditions", "contraindicatedConditions")

# Canonical goals enum — single source of truth: scripts/seed_recipes.py
CANONICAL_GOALS: frozenset[str] = frozenset(
    {"weight_loss", "maintain", "muscle_gain", "weight_gain", "health"}
)

# Tokens that should move from conditions[] → targetGoals[] with canonical mapping.
CONDITION_TO_GOAL_MAP: dict[str, str] = {
    "muscle_recovery": "muscle_gain",
    "muscle_hypertrophy": "muscle_gain",
    "muscle_building": "muscle_gain",
    "build_muscle": "muscle_gain",
    "muscle_preservation": "muscle_gain",
    "post_workout_recovery": "muscle_gain",
    "weight_gain": "weight_gain",
    "weight_management": "maintain",
}

# Singular allergy form missed by prior fix.
EXTRA_ALLERGY_SUFFIX_MAP: dict[str, str] = {
    "tree_nut_allergy": "tree_nuts",
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
    mc = rec.setdefault("matchingCriteria", {})

    diff: dict[str, Any] = {
        "id": rec.get("id"),
        "removed_conditions": {},        # field -> [tokens dropped]
        "moved_to_goals": {},            # field -> {orig_token: canonical_goal}
        "added_allergens": [],           # tokens routed to allergens[]
    }

    # Track goal additions from conditions[] reclassification.
    goals_to_add: set[str] = set()
    allergens_to_add: set[str] = set()

    for fld in CONDITION_FIELDS:
        original = list(mc.get(fld) or [])
        removed: list[str] = []
        moved: dict[str, str] = {}
        kept: list[str] = []

        for tok in original:
            # Canonical condition? keep.
            if tok in CANONICAL_CONDITIONS:
                kept.append(tok)
                continue
            # Singular *_allergy form → allergens.
            if tok in EXTRA_ALLERGY_SUFFIX_MAP:
                allergen = EXTRA_ALLERGY_SUFFIX_MAP[tok]
                allergens_to_add.add(allergen)
                removed.append(tok)
                continue
            # Goal masquerading as condition → goals[].
            if tok in CONDITION_TO_GOAL_MAP:
                canonical_goal = CONDITION_TO_GOAL_MAP[tok]
                goals_to_add.add(canonical_goal)
                moved[tok] = canonical_goal
                continue
            # Anything else: out-of-scope per GR#3 → DROP.
            removed.append(tok)

        kept = _dedup_preserve(kept)
        if kept != original:
            mc[fld] = kept
        if removed:
            diff["removed_conditions"][fld] = removed
        if moved:
            diff["moved_to_goals"][fld] = moved

    # Merge goals.
    if goals_to_add:
        current_goals = list(mc.get("targetGoals") or [])
        merged = _dedup_preserve(current_goals + sorted(goals_to_add))
        # Sanity: every entry must be canonical (existing values may already be).
        canonical_only = [g for g in merged if g in CANONICAL_GOALS]
        if canonical_only != current_goals:
            mc["targetGoals"] = canonical_only

    # Merge allergens (lexicon fix for tree_nut_allergy).
    if allergens_to_add:
        current_allergens = list(mc.get("allergens") or [])
        # Normalise & filter to enum.
        norm = [ALLERGEN_SYNONYMS.get(a, a) for a in current_allergens]
        norm = [a for a in norm if a in ALLERGEN_ENUM]
        merged = sorted(set(norm) | allergens_to_add)
        if merged != current_allergens:
            mc["allergens"] = merged
            diff["added_allergens"] = sorted(allergens_to_add)

    # Empty diff -> no-op record.
    if (not diff["removed_conditions"]
            and not diff["moved_to_goals"]
            and not diff["added_allergens"]):
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

    # Atomic backup (idempotent: skip if backup already exists).
    if not BACKUP_PATH.exists():
        shutil.copy2(CATALOG_PATH, BACKUP_PATH)
    else:
        print(f"backup already exists at {BACKUP_PATH}, skipping copy (idempotent re-run)")

    diffs: list[dict[str, Any]] = []
    counter: Counter[str] = Counter()
    dropped_token_freq: Counter[str] = Counter()
    moved_token_freq: Counter[str] = Counter()

    for rec in records:
        diff = fix_record(rec)
        if diff:
            diffs.append(diff)
            if diff["removed_conditions"]:
                counter["records_with_drops"] += 1
                for fld, toks in diff["removed_conditions"].items():
                    counter[f"dropped_{fld}"] += len(toks)
                    for t in toks:
                        dropped_token_freq[t] += 1
            if diff["moved_to_goals"]:
                counter["records_with_goal_moves"] += 1
                for fld, mapping in diff["moved_to_goals"].items():
                    counter[f"moved_to_goals_{fld}"] += len(mapping)
                    for orig in mapping:
                        moved_token_freq[orig] += 1
            if diff["added_allergens"]:
                counter["records_with_allergens_fixed"] += 1
                counter["allergens_added_lexicon_fix"] += len(diff["added_allergens"])

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
                "canonical_goals_enum": sorted(CANONICAL_GOALS),
                "canonical_conditions_enum_size": len(CANONICAL_CONDITIONS),
                "summary": dict(counter),
                "dropped_token_freq": dict(
                    sorted(dropped_token_freq.items(), key=lambda kv: -kv[1])
                ),
                "moved_token_freq": dict(
                    sorted(moved_token_freq.items(), key=lambda kv: -kv[1])
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
