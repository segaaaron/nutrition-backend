# ADR-0003 — Vision pipeline confidence threshold and prompt versioning

- Status: Accepted
- Date: 2026-05-30
- Deciders: nova-nutrition-backend-architect, nova-qa-elite
- Supersedes: n/a

## Context

`POST /logs/food/photo` returns a vision-extracted item list with a per-item
`confianza ∈ [0, 1]`. The spec previously said *"Match if confianza > 0.7"*
without calibration evidence. A magic constant gates whether a food log
auto-attaches to a verified `foods` row (canonical macros) or is stored as
free-text (estimated macros). A miscalibrated threshold corrupts kcal
totals at scale, which then poisons the recalibration loop (ADR-0002).

The QA mandate requires a Brier score ≤ 0.20 and a reliability diagram before
shipping any `gpt-4o` vision call to production.

## Decision

- **Initial threshold: `0.7`**, encoded as a single constant
  `app/vision/domain/calibration.py::CONFIDENCE_MATCH_THRESHOLD = 0.70`.
- **Calibration regime**: quarterly review. Each review:
  - Runs the current production prompt against a golden set of ≥100 LatAm + US
    dishes with nutritionist ground truth.
  - Produces a reliability diagram committed to `docs/qa/vision-calibration/<yyyy-mm-dd>.png`.
  - Passes only if Brier ≤ 0.20 AND precision-at-threshold ≥ 0.90.
  - Updates the constant only via PR with the new diagram attached.
- **Prompt versioning**: every vision (and coach) prompt lives as a row in
  `ai_prompts(name, version, body, model, params, active)`. Exactly one row per
  `name` may have `active=true` (enforced by partial unique index). Every
  OpenAI call records `prompt_sha256 = sha256(body)` on the resulting row
  (`food_logs.prompt_sha256`, `coach_messages.prompt_sha256`). Postmortems can
  attribute regressions to a specific prompt SHA.
- **Kill-switch**: `feature_flags.vision.enabled=false` short-circuits every
  vision call to 503 without a deploy.

## Consequences

- Threshold drift is a documented quarterly event, not silent code change.
- Postmortem on a bad vision call has a reproducible prompt body via
  `prompt_sha256 → ai_prompts.body`.
- Vision can be disabled in seconds when a regression or cost spike hits.

## References

- Brier GW. *Verification of forecasts expressed in terms of probability*.
  Monthly Weather Review 1950; 78(1):1-3.
- Spec §9.1, §12.
- Tests: `tests/ai/test_vision_calibration.py::test_threshold_meets_precision_floor`,
  `tests/integration/coach/test_prompt_version_recorded.py`,
  `tests/integration/feature_flags/test_kill_switch_blocks_vision.py`.
