# ADR-0016 — Lactation segment lift (H2.1)

**Status:** Accepted
**Date:** 2026-06-01
**Context:** First nutrition segment unlock from the MVP gate per master plan H2.

## Decision

Lift the `lactation` condition from `MVP_BLOCKED_CONDITIONS` and ship the foundation for nutrition segment expansion:

1. `LactationGate` Strategy class registered in `app/plan/domain/condition_gates/`.
2. `apply_lactation_adjustment(kcal_target, conditions)` in `app/plan/domain/bmr_safety.py` — adds Decimal("500") kcal when `"lactation" in conditions`.
3. `app/plan/application/layer1_eligibility.py` dispatches to `gates_for("lactation")` when user has the condition.
4. `app/core/config.py` — `mvp_blocked_conditions` reduced from `"diabetes_t1,diabetes_t2,pregnancy,lactation,ckd"` to `"diabetes_t1,diabetes_t2,pregnancy,ckd"`.

## Why now

Catalog readiness (verified 2026-06-01):
- **200** recipes with `recommended_for_conditions ∋ lactation`
- **200/200** with `folate_ug` populated (target ≥150 μg/portion ⇒ ≥600/day across 4 meals)
- **200/200** with `calcium_mg` populated (≥300/portion ⇒ ≥1000/day)
- **200/200** with `iron_mg` populated (≥4/portion ⇒ ≥16/day)
- All 200 `pregnancy_safe=true` (no raw fish, no soft cheese, no high-Hg fish, no liver/organ, no alcohol)

Master plan H2 minimum was 150. Hit with margin.

## Why lactation BEFORE pregnancy

| Risk axis | Lactation | Pregnancy |
|-----------|-----------|-----------|
| Teratogenic ingredients | None (vitamin A from liver not contraindicated post-partum) | High (mercury, retinol, alcohol) |
| Trimester logic | No trimester variation | +0 / +340 / +452 per trimester |
| Required specialist review | Lactation gates non-life-threatening; document in ADR | Requires OB-GYN sign-off |
| Catalog count | 200 ready | 0 generated |
| Algorithm code change | +1 ConditionGate + 1 kcal adjustment | +trimester field + +trimester adjustment + pregnancy_safe hard exclude + folate ≥600 enforce + iron ≥27 enforce |
| Effort to ship | 3-5 days | 2-3 weeks |

Lactation is the right pattern-validation step. Pregnancy waits for OB-GYN consultation.

## Layer 1 SQL contribution

```sql
(r.pregnancy_safe = TRUE
 AND COALESCE(r.folate_ug, 0) >= 150
 AND COALESCE(r.calcium_mg, 0) >= 300
 AND COALESCE(r.iron_mg, 0) >= 4)
```

`COALESCE(..., 0)` defensive: un-backfilled rows (NULL) fail the threshold and are excluded. **Lactation safety > variety.**

## kcal adjustment formula

```python
if "lactation" in conditions:
    return kcal_target + Decimal("500")
return kcal_target
```

Source: IOM DRI for breastfeeding women, exclusive lactation months 0-6. Single +500 surplus (not trimester-aware — lactation has no trimester). Caller decides whether condition flag means "currently breastfeeding exclusively" — UI must confirm at onboarding.

## Property invariants (tests)

- `non_lactation_passthrough`: 200 random conditions sets without lactation → adjustment no-op (kcal unchanged).
- `lactation_adds_500_kcal`: 200 random kcal values + lactation → output = input + 500.
- `lactation_kcal_at_or_above_tdee_under_deficit`: even with weight_loss goal (deficit), final kcal ≥ TDEE for 200 random women profiles. Protects mother + infant energy floor.
- `lactation_gate_registered_at_import`: registry contains LactationGate at module import time.
- `lactation_gate_contributes_sql_with_thresholds`: SQL fragment + params verified.
- `lactation_gate_coalesces_null_strictly`: COALESCE(0) NULL → reject path verified.
- `layer1_inlines_lactation_gate`: Layer1 source code dispatches to gates_for('lactation').

All 7 pass.

## Telemetry

Add metrics post-launch:
- `plan_generation_total{condition="lactation"}` counter
- `lactation_kcal_target_distribution` histogram
- `lactation_eligibility_recipe_count_per_user` histogram (alert if median <40 → variety collapse risk)
- `lactation_micronutrient_target_hit_pct` gauge (folate/Ca/Fe daily ≥ DRI)

Weekly rollup reviewed for 4 weeks before considering pregnancy unlock.

## Risks accepted

| Risk | Mitigation |
|------|-----------|
| User self-tags lactation without actually breastfeeding | UI confirms "exclusively breastfeeding?" — if no, kcal_target uses +250 fallback OR exits lactation pathway entirely. Future form work. |
| Catalog 200 recipes may feel repetitive | Variety Gini metric on lactation cohort; expand if >0.65. |
| Folate ≥150/portion threshold could exclude valid recipes with high cumulative folate from non-folate-tagged ingredients | Conservative cut acceptable for v1; revisit when micro-backfill from USDA FDC lands. |
| Migration 0008 columns not yet applied to prod DB | COALESCE defensive; once migrated, gate becomes binding. Until then, lactation users get filtered output if columns present, no output if columns absent. Pre-flight check post-deploy ensures migration applied. |
| No OB-GYN sign-off | Document limitation in this ADR. Lactation has lower teratogenic risk than pregnancy; lift acceptable for MVP. Pregnancy stays gated. |

## Files touched

```
NEW:
  app/plan/domain/condition_gates/__init__.py            — auto-register at import
  app/plan/domain/condition_gates/registry.py            — Strategy registry
  app/plan/domain/condition_gates/lactation.py           — LactationGate
  tests/plan/property/test_lactation_invariants.py       — 7 properties
  docs/adr/0016-lactation-segment-lift.md                — this ADR

MODIFIED:
  app/plan/domain/bmr_safety.py                          — +apply_lactation_adjustment
  app/plan/application/layer1_eligibility.py             — +inline lactation gate dispatch
  app/core/config.py                                     — mvp_blocked_conditions: lactation removed
  tests/unit/profile/test_mvp_segment_gate.py            — lactation passes now
```

## Rollback

Single env var flip: `MVP_BLOCKED_CONDITIONS="diabetes_t1,diabetes_t2,pregnancy,lactation,ckd"` re-gates lactation without code change. Code paths remain (no removal); LactationGate stays registered and harmless to non-lactation users.

## Next: pregnancy (H2.2)

Pre-requisites tracked in `docs/algorithms/MASTER_PLAN_ALGORITHM.md`:
- +250 pregnancy recipes generated with OB-GYN review
- `trimester` field added to OnboardingRequest Pydantic schema
- `apply_trimester_adjustment(kcal, trimester)` ships
- `PregnancyGate` Strategy + register
- Hard exclude: raw fish, soft cheese, Hg-high fish, liver/foie, alcohol — strict (no COALESCE-passthrough)
- Folate ≥600 hard daily, iron ≥27, calcium ≥1000
- Specialist review of recipe set

Estimated H2.2 effort: 2-3 weeks. Not started.

## References

- Master plan `docs/algorithms/MASTER_PLAN_ALGORITHM.md` H2.4
- Catalog round 2 report `docs/algorithms/CATALOG_ROUND2_REPORT.md`
- Migration 0008 `migrations/versions/0008_recipe_micronutrients.py`
- ADR-0009 Decimal-strict migration
