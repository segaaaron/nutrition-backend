# ADR-0009 — Decimal-strict plan algorithm migration

**Status:** Accepted
**Date:** 2026-06-01
**Context:** Master plan algorithm refactor (`docs/algorithms/MASTER_PLAN_ALGORITHM.md`)

## Context

The pre-existing nutrition module (`app/nutrition/domain/`) computes BMR (Mifflin-St Jeor), TDEE, macro partitioning, and hydration using a mix of `int` and `float` arithmetic. The legacy `compute_bmr`, `compute_macros`, and `compute_tdee` cast Decimal inputs to `float`, perform IEEE-754 math, then round to `int`. This was acceptable for MVP launch but breaks two non-negotiable engineering principles:

1. **Decimal precision for nutrition math** (CLAUDE.md rule #2). Float introduces non-deterministic rounding at sub-kcal granularity; the bug rarely surfaces but produces silent drift over long recalibration sequences.
2. **Master plan H1 invariants** require:
   - Macro back-adjust within `MACRO_TOLERANCE = Decimal("0.02")` of `target_kcal` (currently met to 0.05% via existing back-adjust loop; not formally tested).
   - BMR safety floor: `kcal_target >= bmr * Decimal("0.9")` (currently violated — existing clamp at 800 kcal can sit below floor for small female users on weight_loss).
   - LBM-anchored protein with optional `bodyfat_pct` (Cunningham). Existing code uses bodyweight-anchored protein only.
   - Fat floor `>= 0.6 * weight` (existing code uses fat-percent only).

## Decision

Two-track strategy:

### Track A — New canonical algorithm modules (this session)

Created Decimal-strict pure-domain modules:

- `app/plan/domain/macro_calculator.py` — `derive_kcal_from_macros`, `compute_carbs_from_kcal_target`, `back_adjust_macros`, `lbm_kg`, `protein_target_g`, `fat_target_g`. All Decimal inputs/outputs. Exceptions: `MacroBackAdjustFailed`, `MacroOutOfRange`.
- `app/plan/domain/bmr_safety.py` — `mifflin_st_jeor`, `cunningham`, `select_bmr`, `tdee`, `apply_goal_to_tdee`, `enforce_bmr_safety_floor`. Exceptions: `KcalTargetBelowSafetyFloor`.

These are the canonical implementations going forward.

### Track B — Defensive instrumentation (this session, non-breaking)

In `app/nutrition/application/use_cases.py`, `_build_goals` now calls `_bmr_safety_warn(...)` after computing `kcal_target`. This logs a structured warning (`kcal_target_below_bmr_safety_floor`) when the legacy path produces a target below the H1.4 safety floor. **It does not raise.** Onboarding remains unchanged for existing users.

### Track C — Future migration (deferred, separate ADR + work)

Plug Track A into the existing flow by:

1. Update `app/nutrition/domain/mifflin_st_jeor.py` to call `app.plan.domain.bmr_safety.mifflin_st_jeor` internally (Decimal-correct, returns same int via final round).
2. Replace `_build_goals` body to use the new functions with `enforce_bmr_safety_floor` raising under feature flag `STRICT_KCAL_SAFETY_FLOOR` (default false → true after telemetry shows acceptable user impact).
3. Update `compute_macros` to use `back_adjust_macros` directly.
4. Deprecate `app/nutrition/domain/macro_partitioning.py` after migration window.
5. Update `app/plan/application/create_plan.py` to consume `MacroTargets` value object from `app/plan/domain/context.py` rather than `dict`.

Migration gating criteria:
- Telemetry: `<5%` of new onboardings hit the safety-floor warning across 30 days.
- For impacted users, manual review + nutrition signoff before flipping `STRICT_KCAL_SAFETY_FLOOR=true`.
- All 15 property invariants in `tests/plan/property/` remain green.

## Consequences

### Positive

- New code is mathematically rigorous and testable in isolation.
- Property invariants enforce mathematical correctness at PR-time.
- Import-linter contract `new plan algorithm modules framework-agnostic` forbids regressions (no FastAPI/SQLAlchemy/Pydantic in new domain code).
- Zero risk to existing users today (Track B is non-breaking).
- Clear migration path with telemetry-driven cutover (Track C).

### Negative

- Two parallel implementations until Track C lands — small risk of behavioral divergence between legacy `compute_bmr` and new `mifflin_st_jeor`. Mitigation: property test `MifflinBounded` verifies the new fn for realistic population; a follow-up cross-check test should compare legacy vs new outputs across population sample (golden delta < 1 kcal).
- Telemetry overhead: warn log on every onboarding. Acceptable (low volume).

### Risks

- Legacy nutrition module sees no behavior change for end users. Users currently receiving `kcal_target < bmr * 0.9` continue receiving the unsafe value. Mitigation: telemetry rollup reviewed weekly; if hits exceed 5%, expedite Track C.
- If Track C is forgotten, the new modules sit unused. Mitigation: master plan owner action items list Track C as P2.

## Alternatives considered

1. **Rip-and-replace nutrition module now.** Rejected: changes user-facing kcal values for existing users without telemetry data on impact. Owner cannot defend regression without baseline.
2. **Add BMR safety floor to existing `_build_goals` raising on violation.** Rejected: breaks existing female weight-loss onboarding flow (small users hit 1189-kcal BMR, floor 1070, weight_loss target 927).
3. **Skip the new modules entirely; refactor legacy in place.** Rejected: legacy float-based code cannot be made Decimal-strict without a full rewrite anyway; doing it twice is wasteful.

## References

- `docs/algorithms/MASTER_PLAN_ALGORITHM.md` — H1 algorithm scope
- `docs/algorithms/PRE_PROD_AUDIT.md` — gaps justification
- `CLAUDE.md` — Decimal precision rule #2
- ADR-0002 — recalibration formula (downstream consumer of Track C)
