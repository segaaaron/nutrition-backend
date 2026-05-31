# ADR-0002 — Dynamic metabolic recalibration formula

- Status: Accepted
- Date: 2026-05-30
- Deciders: nova-nutrition-backend-architect, nova-clinical-nutrition-generator,
  nova-qa-elite
- Supersedes: n/a

## Context

The recalibration loop is the headline clinical differentiator vs Fitia. The
spec previously said `tdee_nuevo = blend(mifflin_recalc, energy_balance_inferred)`
without defining `blend()`, `slope()`, the trigger threshold, or any cool-down.
The two architect agents disagreed on the threshold direction (`<50%` vs `>0.5`).
With an undefined formula no property-based test can exist and two simultaneous
implementations would silently diverge.

## Decision

Lock the recalibration math:

```
inputs (rolling 14d ending at WeightLogged.ts):
  W = [(day_index, peso_kg)]                 # require len(W) >= 7, else SKIP
  K = [kcal_in_day for day in 14d]
  tdee_prev = current nutritional_goals.tdee

slope_kg_per_day      = OLS_linear_regression(W).slope
observed_tdee_inferred = mean(K) - slope_kg_per_day * 7700
mifflin_recalc         = MifflinStJeor(sex, peso_kg_now, talla, edad) * factor_actividad

tdee_nuevo = clamp(
    round( 0.5 * mifflin_recalc + 0.5 * observed_tdee_inferred ),
    tdee_prev * 0.85,
    tdee_prev * 1.15,
)

esperado_kg_dia = (mean(K) - tdee_prev) / 7700
delta_ratio     = slope_kg_per_day / esperado_kg_dia      # skip if |esperado| < 1e-4

TRIGGER iff
    |delta_ratio - 1| > 0.5
    AND n_days_with_weight >= 14
    AND days_since_last_recalibration >= 14                # cool-down
```

Algorithm choices:
- **OLS** over Theil-Sen for the slope: catalog weight series are short (14
  points), normally distributed around the trend, and OLS gives us a closed-form
  variance for confidence reporting. We revisit if outlier sensitivity becomes
  a problem in production telemetry.
- **0.5 / 0.5 blend**: equal weighting between the textbook Mifflin recalculation
  (anchored in physiology) and the observed energy-balance estimate (anchored in
  the user's reality). Tunable per ADR amendment.
- **±15% clamp**: prevents a noisy 14-day window from swinging targets so far
  that the user notices a regime change instead of a refinement.
- **14-day cool-down**: prevents oscillation when two `WeightLogged` events
  straddle the trigger boundary.

## Edge cases

- **Athlete bulk** (`objetivo='ganar_musculo'`): positive slope is intended;
  trigger only when `delta_ratio < 0.5` (under-gaining) or `delta_ratio > 1.5`
  (over-gaining beyond plan), not on the symmetric `0.5 < |delta_ratio - 1|`
  rule. Implemented as a guard in the use case.
- **Post-partum / illness** markers: the use case checks
  `feature_flags.recalibration.enabled` per user; clinicians (or the user) can
  pause recalibration via that flag.
- **Insufficient data** (`< 7` weight points in 14d): SKIP silently, emit
  `recalibration_skipped_total{reason="insufficient_data"}`.
- **Sensor noise / single outlier**: the 14-day `peso_kg` series is winsorised
  at the **5th and 95th percentiles** of the window before OLS. This bounds
  both tails symmetrically (scale-calibration error and fluid swings can deviate
  either way) and removes the need for a per-day σ estimate on a 14-point
  sample where σ itself is noisy. Spec §9.2 carries the same step verbatim;
  the two documents are the single source of truth.

## Consequences

- Property test exists: `|tdee_nuevo - tdee_prev| <= 0.15 * tdee_prev` over the
  full bounded input space.
- Deterministic — same inputs give the same `tdee_nuevo`.
- Two architect agents converge on the same formula.

## References

- Mifflin MD, St Jeor ST. *A new predictive equation for resting energy
  expenditure in healthy individuals*. Am J Clin Nutr 1990; 51(2):241-7.
- Hall KD et al. *Quantification of the effect of energy imbalance on
  bodyweight*. Lancet 2011; 378(9793):826-37 (7700 kcal/kg constant).
- Spec §9.2, §6.
- Tests: `tests/unit/domain/test_recalibration.py::test_blend_function_is_deterministic_and_bounded`,
  `tests/unit/domain/test_recalibration.py::test_athlete_bulk_does_not_trigger`,
  `tests/integration/nutrition/test_recalibration_concurrency.py`.
