# ADR-0022 — Recalibration robustness: winsorise + MAD outliers + intake bias + adaptive thermogenesis

- Status: Accepted
- Date: 2026-06-03
- Deciders: Owner (Miguel Saravia), nova-nutrition-backend-architect, nova-clinical-nutrition-generator, nova-qa-elite
- Supersedes: n/a (extends ADR-0002)
- Tags: nutrition, recalibration, nutrition-safety, robustness

## Context

ADR-0002 locked the recalibration core (`tdee_nuevo = 0.5·mifflin_recalc + 0.5·observed_tdee_inferred`, ±15% clamp, 14-day cool-down, OLS slope on a 14-day weight window). Production telemetry through Sprint 2-3 surfaced four robustness gaps that the core formula did not cover:

1. **Single-day weight outliers** (e.g. post-meal weigh-in, hydration swing, scale-calibration glitch) skewed the OLS slope despite the percentile winsorise note in ADR-0002 §Edge cases.
2. **Self-reported intake under-reports** by 20-30 % on average in free-living adults (Lichtman 1992 NEJM; Hill 2001 Med Sci Sports Exerc), inflating `observed_tdee_inferred` and pulling `tdee_nuevo` upward incorrectly.
3. **Sustained caloric deficits >21 days** produce metabolic adaptation (adaptive thermogenesis, AT) not captured by Mifflin-St Jeor at refreshed body weight (Müller 2015 Obes Facts 8:165).
4. **D7 bug**: the first AT prototype used raw `mean(K)` instead of the bias-corrected intake, double-counting bias in the deficit estimate.

Day-index contract was also ambiguous (local vs UTC); QA flagged drift around DST boundaries for Chile / Mexico / Argentina.

## Decision

Layer the following robustness steps on top of the ADR-0002 core, applied in this strict order before the blend:

```
raw_W, raw_K
  → step 1: winsorise weights at P5 / P95 of the 14-day window
  → step 2: MAD outlier rejection on weights, k = 3
            keep w_i iff |w_i - median(W)| ≤ 3 · MAD(W)
  → step 3: intake physiological floor
            if mean(K_kept) < 0.5 · BMR  → raise IntakeBelowPhysiologicalFloor, SKIP recalibration
  → step 4: intake bias correction
            corrected_mean_K = mean(K_kept) · 1.20      # Lichtman/Hill under-report factor
  → step 5: observed_tdee_inferred = corrected_mean_K - slope_kg_per_day · 7700
  → step 6: blend (ADR-0002 core, unchanged)
            tdee_blended = clamp(round(0.5·mifflin_recalc + 0.5·observed_tdee_inferred),
                                 tdee_prev·0.85, tdee_prev·1.15)
  → step 7: adaptive thermogenesis adjustment
            if days_in_deficit ≥ 21:
                deficit_avg = tdee_blended - corrected_mean_K   # uses corrected intake (D7 fix)
                AT_factor   = max(-0.15, -0.06 · (deficit_avg / tdee_blended) · (days_in_deficit / 14))
                tdee_nuevo  = round(tdee_blended · (1 + AT_factor))
            else:
                tdee_nuevo  = tdee_blended
```

### Day-index contract

`day_index = (event_ts_utc.date() - epoch_utc.date()).days`. Always UTC. Local-time DST shifts never reorder events. The use case never reads `event_ts.date()` without `.astimezone(timezone.utc)` first.

### Declared exceptions

| Exception | When | Behaviour |
|-----------|------|-----------|
| `InsufficientDataForRecalc` | <7 weights after MAD rejection, or <14 intake days | SKIP silently, emit `recalibration_skipped_total{reason="insufficient_data"}` |
| `IntakeBelowPhysiologicalFloor` | corrected_mean_K < 0.5·BMR | SKIP, emit `recalibration_skipped_total{reason="intake_below_floor"}`, surface to coach for low-intake escalation |
| `AdaptiveThermogenesisCapped` | computed AT_factor < -0.15 | clamp to -0.15, emit `recalibration_at_capped_total` |

All three are **fail-skip**, never fail-loud. Recalibration is an enhancement; failing one cycle is acceptable.

## Consequences

### Positive
- Single-day weight glitches no longer move TDEE; MAD k=3 is robust to one extreme point in a 14-point window.
- TDEE estimates become more conservative under self-reported intake, reducing the risk of recommending insufficient calories during weight-loss plateaus.
- Plateau detection improves for users >21 days in deficit; AT model accounts for measured metabolic adaptation rather than blaming user adherence.
- Day-index UTC contract removes DST drift, deterministic across LatAm zones.
- D7 bug closed: AT no longer double-counts bias.

### Negative
- More conservative TDEE → slower goal trajectory adjustments visible to users. Acceptable: under-eating is the safety risk, not slow correction.
- The 1.20 bias factor is population-average; individuals who accurately log are over-corrected by ~10 %. Acceptable bound (still within ADR-0002 ±15 % clamp).
- Three new skip reasons surface as silent metrics; ops dashboard must include them.

### Risk accepted
- AT formula constant (-0.06 per 14-day deficit) is a single-source estimate. Müller 2015 cohort was N=32 European adults; LatAm generalisation unvalidated. Mitigation: -0.15 hard cap, plus blended estimate still bounded by ADR-0002 ±15 % clamp before AT applies.

## References

- Lichtman SW et al. *Discrepancy between self-reported and actual caloric intake and exercise in obese subjects*. NEJM 1992; 327(27):1893-8.
- Hill RJ, Davies PSW. *The validity of self-reported energy intake as determined using the doubly labelled water technique*. Br J Nutr 2001; 85(4):415-30.
- Müller MJ, Enderle J, Bosy-Westphal A. *Changes in energy expenditure with weight gain and weight loss in humans*. Obes Facts 2015; 8(3):165-78.
- Mifflin MD, St Jeor ST. Am J Clin Nutr 1990; 51(2):241-7.
- Hall KD et al. Lancet 2011; 378(9793):826-37.
- Code: `app/nutrition/domain/recalibration.py`, `app/nutrition/domain/mifflin_st_jeor.py`
- Tests: `tests/unit/nutrition/test_recalibration.py` (winsorise, MAD, floor, AT, D7), `tests/unit/nutrition/test_macro_invariants.py`
- Related: ADR-0002 (locked core), ADR-0024 (AT model detail), ADR-0009 (Decimal strictness)
