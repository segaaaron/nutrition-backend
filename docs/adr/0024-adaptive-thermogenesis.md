# ADR-0024 — Adaptive thermogenesis model (Müller 2015)

- Status: Accepted
- Date: 2026-06-03
- Deciders: Owner (Miguel Saravia), nova-nutrition-backend-architect, nova-clinical-nutrition-generator, nova-qa-elite
- Supersedes: n/a (refines ADR-0002, applied by ADR-0022)
- Tags: nutrition, recalibration, nutrition-safety, plateau-handling

## Context

ADR-0002 anchored TDEE on Mifflin-St Jeor recomputed at current body weight, blended 50/50 with energy-balance-inferred TDEE. This works for steady-state and short deficits. It does not capture **adaptive thermogenesis (AT)** — the measurable downward shift in resting and non-resting energy expenditure observed in humans sustaining a caloric deficit beyond ~3 weeks (Müller MJ et al. 2015 Obes Facts 8:165; Rosenbaum & Leibel 2010).

Symptom in NOVA telemetry through Sprint 2: users 25-40 days into a cut report stalled scale weight despite logged adherence. Without an AT term the algorithm interprets the plateau as either (a) under-logging — incorrect for adherent users, or (b) wrong Mifflin baseline — over-corrects and recommends an even sharper cut, increasing drop-out and safety risk (under-eating).

## Decision

Apply an AT correction after the ADR-0002 blend, only when sustained deficit conditions are met:

```python
if days_in_deficit >= 21:
    deficit_avg = tdee_blended - corrected_mean_K          # corrected, per D7 fix (ADR-0022)
    deficit_frac = deficit_avg / tdee_blended              # 0..1 typically
    AT_factor   = max(-0.15, -0.06 * deficit_frac * (days_in_deficit / 14))
    tdee_nuevo  = round(tdee_blended * (1 + AT_factor))
else:
    tdee_nuevo  = tdee_blended
```

### Activation conditions

- `days_in_deficit ≥ 21` — counted as days where `intake_K_day < tdee_prev` over the 14-day window plus the prior 14 days.
- `deficit_frac > 0`. Surpluses skip AT (no symmetric overfeed adaptation modelled in MVP).
- Recalibration window must already have passed the ADR-0022 floor and bias steps (`corrected_mean_K` is the bias-corrected intake mean, never raw).

### Constants

| Constant | Value | Justification |
|----------|-------|---------------|
| Base coefficient | −0.06 per 14-day window | Müller 2015 reported mean -94 ± 87 kcal/d AT at 14 days of 50 % restriction on ~1500 kcal baseline → ~-6 % of TDEE per 14 days at that intensity. |
| Trigger window | 21 days | Conservative; literature shows AT measurable from ~14 days but high variance below 21. |
| Hard cap | −15 % | Matches ADR-0002 ±15 % clamp; AT cannot drive TDEE below 0.85·tdee_prev compounded with the clamp, so the worst-case combined adjustment is bounded. |

### D7 fix coupling

AT_factor uses `corrected_mean_K` (Lichtman/Hill-adjusted intake mean) from ADR-0022 step 4. Using raw mean would double-count under-reporting bias once in `observed_tdee_inferred` and again in `deficit_avg`. Test `test_at_uses_corrected_mean` enforces.

## Consequences

### Positive
- Plateau handling improves materially for adherent users in week 4+. Estimated TDEE drops 4-12 % depending on deficit depth and duration, matching expected physiology.
- Reduces incorrect "cut deeper" recommendations.
- Hard −15 % cap guarantees AT cannot create runaway downward spiral.

### Negative
- Source cohort (Müller 2015) is N=32 European adults at 50 % restriction. LatAm population and milder deficits (~20 %) are extrapolations. Mitigation: hard cap.
- AT term is emitted in plan telemetry but not currently surfaced to users; coach prompt does not yet explain "your metabolism has adapted" — Sprint 4 work.

### Risk accepted
- Over-correction in users whose `corrected_mean_K` under-estimates true intake (i.e. extreme under-loggers). Caps prevent unsafe outcomes; recommend `coach` proactive nudge when AT_factor ≤ −0.10 to verify logging accuracy.
- AT model assumes deficit; users cycling in/out of deficit on weekly basis will see AT activate-deactivate as `days_in_deficit` fluctuates. Acceptable for MVP; refeed-aware AT deferred.

## Failure modes documented

| Mode | Detection | Mitigation |
|------|-----------|------------|
| `corrected_mean_K` under-estimated | AT_factor saturates at −0.15 quickly | `AdaptiveThermogenesisCapped` metric → coach review |
| User exits deficit briefly mid-window | `days_in_deficit` reset breaks AT continuity | Acceptable; AT recomputes next cycle |
| Deficit very mild (`deficit_frac < 0.05`) and long | AT_factor still grows over weeks | Mitigated by 14-week denominator — sub-1 % per cycle, bounded by cap |

## References

- Müller MJ, Enderle J, Bosy-Westphal A. *Changes in energy expenditure with weight gain and weight loss in humans*. Obes Facts 2015; 8(3):165-78.
- Rosenbaum M, Leibel RL. *Adaptive thermogenesis in humans*. Int J Obes 2010; 34(Suppl 1):S47-55.
- Code: `app/nutrition/domain/recalibration.py` (AT block), `app/nutrition/domain/mifflin_st_jeor.py`
- Tests: `tests/unit/nutrition/test_recalibration.py::test_at_activates_after_21_days_deficit`, `::test_at_capped_at_minus_15_percent`, `::test_at_uses_corrected_mean`
- Related: ADR-0002 (recalibration core), ADR-0022 (robustness pipeline), ADR-0009 (Decimal strictness)
