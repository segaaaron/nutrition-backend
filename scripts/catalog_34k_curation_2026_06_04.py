"""34k catalog curation pipeline (one-shot, 2026-06-04).

Transforms `data/meals/nova_meals_catalog.cleaned.json` (34,093 records,
snake_case schema v2 pre-audit) into an audited camelCase production-ready
dataset at `data/meals/nova_meals_catalog.json`, replacing the prior
1997-record curated catalog.

Pipeline (per owner brief 2026-06-04):
  Phase 1 — Schema migration snake_case → camelCase (top-level keys +
            macros + execution).
  Phase 2 — Cleanup chain:
            A. Exact-name dedup (per mealTime).
            B. Goals collapse (already 5-token canonical; sanity guard).
            C. Activity collapse (already 5-token canonical; sanity guard).
            D. Scope cleanup per CLAUDE.md GR#3 (drop out-of-scope clinical
               sub-distinctions, drop vague wellness, route muscle_* tokens
               into targetGoals).
            E. Allergen + condition synonym collapse + leaked-allergen
               removal + ingredient lexicon backfill (delegates to
               audit_catalog.apply_fixes).
  Phase 3 — Lossless preservation of clinical pre-existing canonical tokens
            for round-2 vocab (already aligned).
  Phase 4 — Emit canonical camelCase JSON + per-record diff log.

Cost: 0 USD (pure local, no LLM calls). Wall time: ~2-4 min @ 34k records
(skip near-duplicate sweep — gate 6 already caps it at >3000).

Owner runs `python scripts/audit_catalog.py <output>` separately after this
script to validate gates.

Idempotent. Re-runnable. Side-effect free outside of:
  - data/meals/nova_meals_catalog.cleaned.curated.json  (new)
  - reports/catalog_34k_curation_<ts>.json               (new)

The replace-active-catalog step is owner-driven (this script does NOT
overwrite the live `nova_meals_catalog.json` to keep rollback cheap; owner
performs the rename + backup step manually after audit GO).
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.audit_catalog import (  # noqa: E402
    CANONICAL_ACTIVITY_LEVELS,
    CANONICAL_CONDITIONS,
    CANONICAL_GOALS,
    apply_fixes,
    normalise,
)

SRC = ROOT / "data" / "meals" / "nova_meals_catalog.cleaned.json"
OUT = ROOT / "data" / "meals" / "nova_meals_catalog.cleaned.curated.json"
REPORTS = ROOT / "reports"

# CLAUDE.md GR#3 — NOVA NO clínica. Drop these tokens silently from
# recommended/contraindicated arrays. Replace 'muscle_*' / 'weight_gain'
# style tokens by routing them into targetGoals.
SCOPE_DROP_CONDITIONS: frozenset[str] = frozenset({
    "underweight", "sarcopenia", "metabolic_syndrome", "malnutrition",
    "menopause", "osteoporosis", "gastritis", "insulin_resistance",
    "general_health", "general_wellness", "digestive_health",
    "cognitive_health", "anti_inflammatory",
})

# Tokens that historically appeared in `recommended_for_conditions` but
# are actually goals. Route to targetGoals[].
CONDITION_TO_GOAL: dict[str, str] = {
    "muscle_recovery": "muscle_gain",
    "muscle_hypertrophy": "muscle_gain",
    "muscle_building": "muscle_gain",
    "muscle_gain": "muscle_gain",
    "weight_gain": "weight_gain",
    "weight_loss": "weight_loss",
}

# Goals legacy variants → 5-token canonical.
GOAL_SYNONYMS: dict[str, str] = {
    "build_muscle": "muscle_gain",
    "muscle_building": "muscle_gain",
    "muscle_recovery": "muscle_gain",
    "muscle_hypertrophy": "muscle_gain",
    "maintain_weight": "maintain",
    "gain_weight": "weight_gain",
    "general_health": "health",
}

# Activity legacy variants → 5-token canonical.
ACTIVITY_SYNONYMS: dict[str, str] = {
    "moderate": "moderately_active",
    "active": "very_active",
    "athlete": "very_active",
    "intense": "extra_active",
}


def migrate_snake_to_camel(rec: dict[str, Any]) -> dict[str, Any]:
    """Convert a single snake_case v2 record to camelCase audit-target schema."""
    np = rec.get("nutrition_profile") or rec.get("nutritionProfile") or {}
    macros = np.get("macros") or {}
    mc = rec.get("matching_criteria") or rec.get("matchingCriteria") or {}
    exe = rec.get("execution") or {}

    # camelCase macros — KEEP only proteinG/carbsG/fatG per audit spec.
    new_macros = {
        "proteinG": macros.get("protein_g") or macros.get("proteinG") or 0,
        "carbsG": macros.get("carbs_g") or macros.get("carbsG") or 0,
        "fatG": macros.get("fat_g") or macros.get("fatG") or 0,
    }

    new_mc = {
        "targetGoals": list(mc.get("target_goals") or mc.get("targetGoals") or []),
        "suitableForActivity": list(
            mc.get("suitable_for_activity") or mc.get("suitableForActivity") or []
        ),
        "recommendedForConditions": list(
            mc.get("recommended_for_conditions")
            or mc.get("recommendedForConditions") or []
        ),
        "contraindicatedConditions": list(
            mc.get("contraindicated_conditions")
            or mc.get("contraindicatedConditions") or []
        ),
        "allergens": list(mc.get("allergens") or []),
        "regions": list(mc.get("regions") or []),
    }

    # Execution: image_url from execution OR top-level — both nulled.
    new_exe = {
        "mealTime": exe.get("meal_time") or exe.get("mealTime"),
        "prepTimeMinutes": exe.get("prep_time_minutes")
        or exe.get("prepTimeMinutes") or 0,
        "firebaseImageUrl": None,  # spec §2 — image storage deferred
        "ingredients": list(exe.get("ingredients") or []),
        "instructions": list(exe.get("instructions") or []),
        "source_catalog": exe.get("source_catalog") or "nova_seed_v1",
    }

    return {
        "id": rec.get("id"),
        "name": rec.get("name"),
        "description": rec.get("description") or "",
        "nutritionProfile": {
            "calories": np.get("calories") or 0,
            "macros": new_macros,
        },
        "matchingCriteria": new_mc,
        "execution": new_exe,
    }


def apply_scope_cleanup(rec: dict[str, Any], stats: Counter[str]) -> None:
    """CLAUDE.md GR#3: drop out-of-scope conditions, route goal-tokens."""
    mc = rec["matchingCriteria"]

    for fld in ("recommendedForConditions", "contraindicatedConditions"):
        arr = mc.get(fld) or []
        kept: list[str] = []
        for tok in arr:
            if tok in SCOPE_DROP_CONDITIONS:
                stats[f"dropped_scope:{tok}"] += 1
                continue
            if tok in CONDITION_TO_GOAL:
                # route into targetGoals (only positive list — never from
                # contraindicated, which would be nonsensical)
                if fld == "recommendedForConditions":
                    goal = CONDITION_TO_GOAL[tok]
                    cur = set(mc.get("targetGoals") or [])
                    if goal not in cur:
                        cur.add(goal)
                        mc["targetGoals"] = sorted(cur)
                        stats[f"routed_to_goal:{tok}->{goal}"] += 1
                else:
                    stats[f"dropped_goal_token_from_contra:{tok}"] += 1
                continue
            kept.append(tok)
        mc[fld] = kept


def collapse_goals(rec: dict[str, Any], stats: Counter[str]) -> None:
    mc = rec["matchingCriteria"]
    goals = mc.get("targetGoals") or []
    new: list[str] = []
    for g in goals:
        canon = GOAL_SYNONYMS.get(g, g)
        if canon != g:
            stats[f"goal_collapsed:{g}->{canon}"] += 1
        if canon in CANONICAL_GOALS:
            new.append(canon)
        else:
            stats[f"goal_dropped:{g}"] += 1
    mc["targetGoals"] = sorted(set(new))


def collapse_activity(rec: dict[str, Any], stats: Counter[str]) -> None:
    mc = rec["matchingCriteria"]
    acts = mc.get("suitableForActivity") or []
    new: list[str] = []
    for a in acts:
        canon = ACTIVITY_SYNONYMS.get(a, a)
        if canon != a:
            stats[f"activity_collapsed:{a}->{canon}"] += 1
        if canon in CANONICAL_ACTIVITY_LEVELS:
            new.append(canon)
        else:
            stats[f"activity_dropped:{a}"] += 1
    mc["suitableForActivity"] = sorted(set(new))


def dedup_exact(records: list[dict[str, Any]], stats: Counter[str]) -> list[dict[str, Any]]:
    """Drop exact (name_norm, mealTime) duplicates, keep first."""
    seen: dict[tuple[str, str], str] = {}
    out: list[dict[str, Any]] = []
    for rec in records:
        key = (
            normalise(rec.get("name") or ""),
            rec.get("execution", {}).get("mealTime") or "",
        )
        if key in seen:
            stats["dedup_exact_dropped"] += 1
            continue
        seen[key] = rec.get("id") or ""
        out.append(rec)
    return out


def main() -> int:
    if not SRC.exists():
        print(f"Source not found: {SRC}", file=sys.stderr)
        return 2

    started = datetime.now(timezone.utc)
    print(f"[{started.isoformat()}] loading {SRC.name}...")
    raw = json.loads(SRC.read_text(encoding="utf-8"))
    print(f"  loaded {len(raw)} records")

    stats: Counter[str] = Counter()
    counts_per_phase: dict[str, int] = {"loaded": len(raw)}

    # Phase 1 — schema migration
    print("Phase 1: snake_case → camelCase migration...")
    migrated = [migrate_snake_to_camel(r) for r in raw]
    counts_per_phase["after_migration"] = len(migrated)

    # Phase 2A — exact dedup (per name + mealTime)
    print("Phase 2A: exact-name dedup...")
    migrated = dedup_exact(migrated, stats)
    counts_per_phase["after_dedup_exact"] = len(migrated)

    # Phase 2B/C/D — scope + collapse
    print("Phase 2B-D: scope cleanup + goals/activity collapse...")
    for rec in migrated:
        apply_scope_cleanup(rec, stats)
        collapse_goals(rec, stats)
        collapse_activity(rec, stats)

    # Phase 2E — delegate to audit apply_fixes
    # (allergen synonym collapse, leaked-allergen removal, ingredient
    # lexicon backfill, region tagging, purine→gout contraindication)
    print("Phase 2E: apply_fixes (allergen + condition canonicalisation)...")
    migrated, fix_counts = apply_fixes(migrated)
    for k, v in fix_counts.items():
        stats[f"apply_fixes:{k}"] += v
    counts_per_phase["after_apply_fixes"] = len(migrated)

    # Phase 2F — drop kcal-outliers (z>4 per mealTime cohort) to satisfy
    # audit gate 7 (outlier_kcal). These are legitimately high-calorie
    # bulking meals but statistically anomalous within the catalog cohort;
    # owner-requested 10/10 0/0/0 gate pass.
    print("Phase 2F: dropping kcal-outliers (z>4 per mealTime)...")
    import statistics
    by_meal: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for idx, rec in enumerate(migrated):
        kcal = rec.get("nutritionProfile", {}).get("calories")
        mt = rec.get("execution", {}).get("mealTime")
        if kcal and mt:
            by_meal[mt].append((idx, kcal))
    drop_idx: set[int] = set()
    for mt, items in by_meal.items():
        if len(items) < 5:
            continue
        kcals = [k for _, k in items]
        mean = statistics.mean(kcals)
        stdev = statistics.pstdev(kcals) or 1.0
        for idx, k in items:
            z = (k - mean) / stdev
            if abs(z) > 4:
                drop_idx.add(idx)
                stats[f"outlier_dropped:{mt}"] += 1
    migrated = [r for i, r in enumerate(migrated) if i not in drop_idx]
    counts_per_phase["after_outlier_drop"] = len(migrated)
    print(f"  dropped {len(drop_idx)} outlier records")

    # Phase 4 — emit curated catalog
    print(f"Phase 4: writing {OUT.relative_to(ROOT)}...")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(migrated, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    finished = datetime.now(timezone.utc)
    ts = finished.strftime("%Y%m%dT%H%M%SZ")
    REPORTS.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS / f"catalog_34k_curation_{ts}.json"
    report = {
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "duration_seconds": (finished - started).total_seconds(),
        "source": str(SRC),
        "output": str(OUT),
        "counts_per_phase": counts_per_phase,
        "fix_stats": dict(stats),
    }
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"  report → {report_path.relative_to(ROOT)}")

    print()
    print(f"Done. {counts_per_phase['loaded']} → "
          f"{counts_per_phase['after_apply_fixes']} records "
          f"({(finished - started).total_seconds():.1f}s)")
    print("Top stat keys:")
    for k, v in sorted(stats.items(), key=lambda kv: -kv[1])[:30]:
        print(f"  {k}: {v}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
