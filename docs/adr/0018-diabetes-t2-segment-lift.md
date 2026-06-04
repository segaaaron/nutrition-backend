# ADR-0018 — Diabetes T2 segment lift (H2.2)

**Status:** Accepted (shipped 2026-06-01)
**Context:** Following lactation lift (ADR-0016), the same Strategy + lift pattern unlocks declared diabetes_t2 users.

## Decision

Lift `diabetes_t2` from `MVP_BLOCKED_CONDITIONS`. Strategy + Layer 1 SQL gate per `app/plan/domain/condition_gates/diabetes_t2.py`:

- `sugar_g ≤ 15` per portion
- `carbs_g ≤ 45` per portion
- `gl ≤ 10` per portion (when populated)
- `fiber_g ≥ 4` per portion

## Why now

Catalog readiness:
- 974 recipes `recommended_for: diabetes_t2` (round 1 + 2 + 3 batches)
- 24 recipes `contraindicated_for: diabetes_t2` (high-carb derecommended)

NOVA scope (ADR-0017): nutrition planning, not nutrition guidance. Diabetic users self-declare their condition. Layer 1 safety floor prevents glycemic harm regardless of nutrition-advice scope. Disclaimer covers liability.

## Consequences

- Diabetic users sign up + receive plans filtered through the GL gate.
- Telemetry post-launch: track diabetes_t2 cohort kcal adherence + recipe variety.
- Rollback: env var `MVP_BLOCKED_CONDITIONS="diabetes_t1,diabetes_t2,..."` re-gates.

## References

- `app/plan/domain/condition_gates/diabetes_t2.py`
- `app/plan/application/layer1_eligibility.py`
- `app/core/config.py::mvp_blocked_conditions`
- ADR-0016 (lactation lift pattern)
- ADR-0017 (scope statement)
