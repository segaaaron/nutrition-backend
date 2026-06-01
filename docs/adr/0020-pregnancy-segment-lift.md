# ADR-0020 — Pregnancy segment lift (H2.6)

**Status:** Accepted (shipped 2026-06-01)

## Decision

Lift `pregnancy` from `MVP_BLOCKED_CONDITIONS`. Strategy: `app/plan/domain/condition_gates/pregnancy.py`. Trimester field added to `OnboardingRequest` schema. Trimester-aware kcal adjustment: `apply_trimester_adjustment(+0/+340/+452)` in `app/plan/domain/bmr_safety.py`.

Layer 1 SQL gate:
- `pregnancy_safe = TRUE` (no raw fish, no soft cheese, no high-Hg fish, no liver, no alcohol)
- `folate_ug ≥ 150` per portion (DRI ≥600 ug/day across 4 meals)
- `iron_mg ≥ 4`
- `calcium_mg ≥ 250`

## Why lift now (no +250 pregnancy-specific recipes)

NOVA scope per ADR-0017: nutrition planning, not clinical advice. The 26,827 `pregnancy_safe = true` recipes already in catalog form a safe filter pool. Adding +250 pregnancy-recommended recipes (boost ranking) is a future quality improvement, NOT a safety prerequisite.

Layer 1 safety floor + micros thresholds + pregnancy_safe filter cover the legal-critical floor. Trimester-aware kcal surplus aligns plan energy with IOM DRI guidance.

## Why no OB-GYN review

NOVA does not prescribe — it filters catalog and computes kcal targets. Disclaimer on signup + per-plan footer redirects to doctor for medical decisions. This is the standard scope for consumer nutrition apps (Yazio, Lifesum, Lose It, etc.).

## Mobile UX (per ONBOARDING_API_CONTRACT.md)

When user selects "Embarazo" chip:
1. Show trimester picker (mandatory): `[1er] [2do] [3er]`
2. Submit fails 422 with `trimester_required_for_pregnancy` if missing
3. Show disclaimer prominently: "Consulta a tu médico durante el embarazo."

## Trimester surplus formula

| Trimester | kcal/day surplus | Source |
|-----------|-----------------:|--------|
| 1st | +0 | IOM DRI 2002 (no increase warranted) |
| 2nd | +340 | IOM DRI 2002 |
| 3rd | +452 | IOM DRI 2002 |

Applied on top of TDEE × goal-adjustment, then capped by BMR safety floor (final kcal ≥ BMR × 0.9 still enforced).

## Consequences

- Pregnant users sign up + receive plans filtered through the safety gate.
- Telemetry mandatory: kcal target distribution per trimester, eligibility recipe count, micronutrient daily targets hit-rate.
- Roll-back: env var or remove pregnancy from `MVP_BLOCKED_CONDITIONS`.

## Future work

- Add +250 pregnancy-specific high-folate recipes (boost ranking, not safety).
- Telemetry-driven decision on `is_exclusively_breastfeeding` extension to partial-pregnancy nutrition states.

## References

- `app/plan/domain/condition_gates/pregnancy.py`
- `app/plan/domain/bmr_safety.py::apply_trimester_adjustment`
- `app/profile/presentation/schemas.py::OnboardingRequest.trimester`
- ADR-0016 lactation lift pattern
- ADR-0017 scope statement
- Migration 0010 user_profiles trimester column
