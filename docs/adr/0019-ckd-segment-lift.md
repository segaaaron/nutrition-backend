# ADR-0019 — CKD segment lift (H2.3)

**Status:** Accepted (shipped 2026-06-01)

## Decision

Lift `ckd` from `MVP_BLOCKED_CONDITIONS`. Strategy: `app/plan/domain/condition_gates/ckd.py`.

Layer 1 SQL gate:
- `potassium_mg ≤ 400` per portion
- `phosphorus_mg ≤ 300`
- `sodium_mg ≤ 500`
- `protein_g ≤ 25`

Defensive COALESCE: un-backfilled micros default to **9999** (fail strictly) for K + P. Safety > variety — hyperkalemia is acute.

## Why now

Catalog readiness:
- 313 recipes `recommended_for: ckd` with K + P populated (round 1 + 2 batches)
- 510 recipes `contraindicated_for: ckd` (high-K + high-P recipes defensively tagged)

## Consequences

- CKD users sign up + receive plans filtered through K + P thresholds.
- Telemetry: track CKD cohort adherence + eligibility recipe count per user (alert if median <20 → variety collapse, expand catalog).

## References

- `app/plan/domain/condition_gates/ckd.py`
- ADR-0017 scope statement
- Migration 0008 (potassium_mg + phosphorus_mg columns)
