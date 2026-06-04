# ADR-0025 — Vision cascade calibration gate

- Status: Proposed
- Date: 2026-06-03
- Deciders: Owner (Miguel Saravia), nova-nutrition-backend-architect, nova-qa-elite
- Supersedes: n/a (refines ADR-0021)
- Tags: vision, cost, calibration, release-gate

## Context

ADR-0021 shipped the four-layer vision pipeline (prefilter → SHA256 cache → cascade primary → confidence fallback). The cost-critical lever is `VISION_CASCADE_ENABLED`. With the flag ON the projected cost drops 81.8 % ($0.005 → $0.00084 per photo, weighted mix). The flag ships **default OFF** because mini-model precision on LatAm dishes is unvalidated and a silent macro error in production is nutritionally meaningful (users dose insulin / titrate intake against returned macros — even outside diabetes_t1 scope, macro accuracy underpins recalibration).

ADR-0021 listed an informal gate ("golden set + eval"). This ADR formalises the gate as auditable acceptance criteria so the flag can be flipped without revisiting design.

## Decision

`VISION_CASCADE_ENABLED=true` requires **all five** gates green, signed off by owner:

### Gate 1 — Golden set curation

- ≥ 100 LatAm dishes photographed under realistic conditions (phone camera, household plate, mixed lighting).
- Each entry has verified ground truth: item list, gram weights per item, kcal, protein_g, carbs_g, fat_g.
- Verification by nova-clinical-nutrition-generator review + spot-check against catalog values.
- Coverage requirement: ≥ 60 dishes from MX/AR/CL/PE/CO catalogs proportional to expected user mix.
- Storage: `data/golden/vision_latam_v1.jsonl` (out of repo, S3-style external).

### Gate 2 — Kcal MAE ≤ 15 %

- Mean absolute error in kcal across the golden set, mini-primary pipeline vs ground truth.
- 15 % is the same envelope as the recalibration ±15 % clamp (ADR-0002), keeping vision noise within the same tolerance band the downstream algorithm already absorbs.

### Gate 3 — Per-ingredient recall ≥ 0.85

- For each ground-truth item, the mini-primary returns an item whose `matched_food_id` matches (or whose `name_norm` matches via the matcher).
- 0.85 chosen because below this the cascade fallback would trigger so often that cost savings collapse.

### Gate 4 — Confidence calibration error ≤ 0.10

- Brier score of the per-item `confidence` field against the binary correct/incorrect outcome.
- ≤ 0.10 means the 0.7 threshold in the fallback condition is meaningful (model knows when it does not know).

### Gate 5 — 7-day production shadow run

- Both pipelines run in parallel on real production traffic (mini-primary results stored but **not** returned to user; gpt-4o full remains source of truth).
- Compare item lists, kcal, macros, confidences.
- Gate passes when:
  - Divergence in returned items <5 % (Jaccard distance per photo, median).
  - No nutrition-tier discrepancies (e.g. mini misses dairy on a hyperchol user's plate).
  - Zero ErrorTracker-captured vision errors attributable to the mini pipeline.

### Sign-off artefact

`docs/adr/0025-flip-evidence.md` (to be created at flip time) captures golden set hash, eval script run output, shadow-run summary, owner signature. Until that file exists, the flag stays OFF.

## Consequences

### Positive
- Auditable. Future contributors cannot flip the flag on intuition.
- Cost remains predictable: until flip, vision spend is single-call gpt-4o full (already cost-capped by ADR-0004 daily budget).
- Decouples the engineering work (already shipped, ADR-0021) from the calibration work (data, ground truth, eval).

### Negative
- Calibration is non-trivial labour. Golden set curation alone is ~40 hours of work plus specialist review. No volunteer pipeline exists; nova-clinical-nutrition-generator drives it once owner schedules.
- Until flipped NOVA pays full gpt-4o per photo. At pre-launch traffic this is sub-$5/month; sustainable for now.
- Catalog dependency: golden set ground truth must reference canonical catalog `food_id`s, so catalog stability is a prerequisite.

### Risk accepted
- Gates are quantitative but eval scripts themselves are not yet written. Sprint 3 work item: `scripts/vision_eval.py` consuming `data/golden/vision_latam_v1.jsonl`.
- 7-day shadow run doubles vision cost during that window. Bounded and acceptable (single week, cost cap absolute limit).

## Status timeline

- 2026-06-03: Proposed, flag remains OFF.
- Gate completion: target Sprint 4-5, depends on golden-set curation slot.
- Acceptance trigger: `docs/adr/0025-flip-evidence.md` lands + owner flips `VISION_CASCADE_ENABLED=true` in Dokploy env.

## References

- ADR-0021 (vision cascade + prefilter — engineering)
- ADR-0003 (vision confidence threshold)
- ADR-0004 (OpenAI cost cap — absolute budget)
- ADR-0006 (model selection matrix)
- Code: `app/vision/infrastructure/openai_vision.py`, `app/vision/application/process_vision_job.py`
- Future scripts: `scripts/vision_eval.py`, `scripts/curate_golden_set.py`
- Data (external): `data/golden/vision_latam_v1.jsonl`
