# ADR-0004 — Per-user and per-org OpenAI cost cap

- Status: Accepted
- Date: 2026-05-30
- Deciders: nova-nutrition-backend-architect, nova-qa-elite
- Supersedes: spec §19 open follow-up *"Decide cost cap policy for OpenAI"*

## Context

`POST /logs/food/photo` (vision) and `POST /coach/chat` (streaming chat) both
hit `gpt-4o`. The existing 60/min per-user rate limit caps requests **per minute**,
not **per day**. A single user submitting one photo per minute for 24h is
1440 vision calls ≈ USD 15 at current pricing — and the abuse case (scripted
client, 5/min) reaches five-figure bills in 24h. No mechanism to stop the bleed
without a deploy.

## Decision

Two layers of cost cap, both backed by Redis sorted sets and the
`feature_flags` table:

- **Per-user daily hard cap**: USD **1.50** by default.
  Key: `cost:user:{user_id}:{yyyymmdd}`, TTL 48h. Every OpenAI call increments
  the key by `prompt_tokens*in_price + completion_tokens*out_price + image_units*image_price`
  (priced from `app/ai/pricing.py`, versioned). When the key value crosses
  `1.50` the dispatcher returns **429** with body
  `{"detail":"daily_cost_cap_exceeded"}`, headers `Retry-After: <s_to_midnight_utc>`
  and `X-Cost-Limit-Reset: <epoch>`. The cap may be raised per user via
  `feature_flags` payload (e.g. paid tier).
- **Per-org global daily cap**: configurable via
  `feature_flags.cost_cap.global_kill` payload `{ "usd_daily": <float> }`.
  Same 429 response when crossed.
- **Kill-switch**: `feature_flags.cost_cap.global_kill.enabled=true` short-circuits
  every `/ai/*` and `/coach/*` endpoint to 503 immediately (`Retry-After: 60`)
  — used during cost incidents.
- **Alerts**: page on `openai_cost_usd_total[1d] >= 0.8 * cap` for the org;
  warn on per-user at 80% via in-app banner (no page).

## Consequences

- Worst-case daily AI spend bounded to `N_users * 1.50 + slack`.
- A runaway abuse case is blocked without a deploy (kill-switch flag flip).
- Cost telemetry (`openai_cost_usd_total`) becomes a first-class metric, not an
  invoice-time surprise.
- Failure mode if Redis is down: dispatcher fails **closed** (returns 503),
  not open — we prefer a brief outage to a cost incident.

## References

- OpenAI public pricing (snapshotted in `app/ai/pricing.py`, refreshed by
  manual PR when OpenAI changes prices).
- Spec §12 (security), §13 (observability).
- Tests: `tests/integration/coach/test_daily_token_cap.py::test_cap_blocks_request_with_429`,
  `tests/integration/feature_flags/test_kill_switch_blocks_vision.py`.
