# ADR-0021: Vision pipeline — hybrid cascade + food prefilter

- Status: Proposed
- Date: 2026-06-03
- Deciders: Owner (Miguel Saravia)
- Tags: vision, cost, scalability, scope

## Context

NOVA's photo → macros endpoint used `gpt-4o-2024-08-06` always-on with `detail: "high"`. Projected cost at 1000 active users with realistic distribution (weighted 6-8 photos/user/day, power-law) was ~$1,050/month — unsustainable vs competitors:

- Fitia (LatAm leader, Y Combinator): photo is PREMIUM, free tier blocked from photo entirely, 4 meals/day cap free.
- MyFitnessPal: photo via Passio AI SDK on-device, premium-gated.
- Yazio, Lifesum: photo premium-gated, slow.
- Indie apps (Macroscanner, Cal AI): use GPT-4o vision directly, subscription priced to absorb cost.

Pattern across industry: **nobody offers GPT-4o photo unlimited for free.** Either premium gate or vendor SDK on-device.

NOVA needed:
1. Drastic cost reduction without losing LatAm accuracy.
2. Reject non-food photos (supplements, water, pills) before paying for full vision call.
3. Backward-compatible rollout (revert without redeploy).

## Decision

Implement four-layer cost strategy, all behind feature flags:

### Layer 0 — Food prefilter (default ON)
`gpt-4o-mini` with `detail: "low"` (85 image tokens) classifies image as food vs non-food before main pipeline. Rule: ACCEPT if ready-to-consume AND ≥20 kcal estimated. REJECT pills, capsules, supplements, vitamins, water, plain coffee/tea, non-food objects, empty plates.

- Cost: ~$0.0001/photo
- Saved on reject: ~$0.005/photo
- Break-even: >2% reject rate
- Fail-open on parse/upstream errors (infrastructure flake never blocks legitimate uploads)

### Layer 1 — SHA256 dedup cache (always on)
Same compressed image within 90 days → reuse stored items.
- PII strip: `matched_food_id`, `matched_name_norm`, `match_method` removed before cross-user return.
- Per-user matcher re-runs on cache hit for personal food matching.
- Cache key includes current prompt SHA so template changes invalidate.

### Layer 2 — Cascade primary (default OFF until golden-set calibration)
`gpt-4o-mini` (high detail) is the primary call. Cheaper, mostly accurate on universal foods.

### Layer 3 — Confidence-based fallback (default OFF)
Escalate to `gpt-4o-2024-08-06` if avg confidence < 0.7 OR min < 0.5 OR items empty. Catches LatAm-specific dishes where mini may underperform.

### Auxiliary
- Auto-detect image `detail` (low if <500×500, else high).
- `max_tokens=1200` cap output, prevents runaway dense plates.
- `json.JSONDecodeError` returns `[]` so cascade escalates instead of hard-failing.
- Redis SETNX inflight lock prevents duplicate billing on concurrent submits.
- Rate limit 30 photos/hour/user (Redis sliding window, fail-closed 503 on Redis outage).
- Pillow decode wrapped in `asyncio.to_thread` to keep event loop responsive.

### Backward compatibility
`VISION_CASCADE_ENABLED=false` → behavior identical to legacy single gpt-4o call. Cache + prefilter + rate limit still active.

## Consequences

### Positive
- **Projected cost: -81.8%** when cascade flag flipped ($0.005 → $0.00084/photo, weighted mix).
- Prefilter alone saves ~5%+ on bad uploads regardless of cascade state.
- Backward compatible rollback (toggle env var, no redeploy of code).
- Defensive against runaway costs (rate limit, max_tokens, cost cap pre-check).

### Negative
- Latency p95 worse when fallback triggers (~5-10s vs ~3s single-call).
- When cascade escalates, user is charged for both calls (mini + gpt-4o). Acceptable transparency.
- Mini classification of LatAm dishes is unvalidated until golden set ships → cascade flag blocked OFF.
- Cache cross-user reuse requires careful PII stripping (mitigated by repo-level strip + use-case rerun).
- Confidence threshold 0.7 is uncalibrated — placeholder until golden set.

### Risk accepted
- Mini overconfident misclassification → mitigated by threshold 0.7 + golden set calibration + instant rollback via flag.
- Cache cross-user PII → mitigated by strip + per-user re-match in use case.
- Dense plate truncation → mitigated by max_tokens=1200 + JSONDecodeError graceful fallback.

## Alternatives considered

### Full OSS stack (YOLOv8-seg + Food-101 + MiDaS depth)
Rejected for MVP. 6-9 eng-weeks + $4-8k data ops. LatAm coverage poor without fine-tune (Food-101 is ~90% US/EU/Asia). Reconsider when vision spend >$300/month sustained.

### Passio AI SDK on-device
Deferred. License $15-50k/year. Reconsider when vision spend >$300/month sustained OR when iOS app maturity demands sub-second latency.

### Keep gpt-4o full always-on
Rejected. Cost unsustainable past ~300 active users.

### Switch to gpt-4o-mini full always-on (no cascade)
Rejected. Mini precision on LatAm dishes is unvalidated; switching without golden set risks silent macro errors.

## Gate to flip `VISION_CASCADE_ENABLED=true`

Before enabling cascade in production:
1. Golden set of ≥100 real LatAm + US + EU photos with ground truth (items + grams + macros).
2. Eval script comparing mini vs full on same set.
3. Metrics gate:
   - MAE kcal ≤ baseline gpt-4o + 15%
   - Top-1 food accuracy ≥ 75% on LatAm subset
   - Brier score ≤ 0.20 (model is well-calibrated)
   - 0 incidents in shadow-run on production traffic (1 week minimum)
4. Owner ADR amendment authorising the flip.

## Pipeline summary post-decision

```
Photo upload
  → rate-limit (30/hour/user, Redis sliding window)
  → prefilter (gpt-4o-mini, low detail, ~$0.0001)
     ├─ REJECT → 422 not_food_image:<reason>
     └─ ACCEPT
        → SHA256 cache lookup
           ├─ HIT → reuse items, re-run matcher per user
           └─ MISS → SETNX inflight lock
              → primary call (gpt-4o-mini if cascade ON, else gpt-4o full)
              → if low confidence AND cascade ON → fallback gpt-4o
              → persist items + cache for 90 days
        → matcher → food_logs insert → FoodPhotoLogged event
```

## References

- Code: `app/vision/infrastructure/openai_vision.py`, `app/vision/application/{process_vision_job,submit_photo}.py`, `app/vision/infrastructure/repositories.py`, `app/vision/presentation/{router,rate_limit}.py`
- Migration: `migrations/versions/0011_vision_jobs_sha_idx.py`
- Tests: `tests/unit/vision/` (126 tests, 92.72% coverage), `tests/integration/vision/` (8 tests, Docker-gated)
- QA audit: nova-qa-elite report 2026-06-03 (GO with caveats — flag blocked until golden set)
- Related: ADR-0003 (vision confidence threshold), ADR-0004 (OpenAI cost cap), ADR-0006 (model selection)
- Industry research:
  - Fitia premium: $19.99/mo, $59.99/yr, $89.99/family — photo premium-only
  - MyFitnessPal: Passio AI SDK on-device, premium
  - Yazio/Lifesum: photo premium-gated
