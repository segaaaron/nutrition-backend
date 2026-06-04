# ADR-0026 — Leaderboard anti-cheat (layered defenses)

- Status: Proposed
- Date: 2026-06-04
- Deciders: Owner (Miguel Saravia), nova-backend-architect, nova-qa-elite
- Supersedes: n/a
- Tags: gamification, leaderboard, abuse, anti-cheat, feature-flag

## Context

`app/gamification/` ships streaks, achievements, XP/levels and a Redis-sorted-set leaderboard keyed by `country:period`. The endpoint `GET /gamification/leaderboard` (`app/gamification/presentation/router.py:70-89`) is gated by the DB feature flag `leaderboard_enabled`, currently **OFF**.

PROJECT_STATE lists "Anti-cheat for leaderboard gated behind feature flag — leaderboard cannot ship live until abuse model exists" as a known blocker. Owner wants the leaderboard shippable to closed-beta (≤100 users, solo dev, pre-revenue).

Threat surface — XP/rank inflation by:

1. Fake text quick-logs (no photo, no scale receipt; user invents meals).
2. Fake weight logs (claim adherence trajectory they did not achieve).
3. Photo replay (same SHA256 or near-duplicate uploaded repeatedly to harvest photo-XP).
4. Streak boundary farming (log at 23:59 local + 00:01 local to chain two days from one human session).
5. Achievement collusion (multi-account follow/cheer rings to unlock social achievements).
6. Sock-puppet accounts (one human, N accounts, ranks 1..N on a small leaderboard).
7. Region spoofing (claim small-country leaderboard, e.g. UY/BO, to top it trivially).

No ML budget. No captcha vendor. Closed-beta scale. Defences must be **deterministic, cheap, owner-auditable, reversible**.

## Decision

Three layers, all behind sub-flags under the master flag `leaderboard_enabled`. Each layer ships independently and can be disabled without redeploy.

### Layer 1 — Hard caps and rate limits (synchronous, in use case)

Enforced inside the **application use case** that awards XP (not in middleware — middleware cannot see semantic event type). Caps are Redis-backed counters keyed by `xp:cap:<user>:<bucket>:<utc_date>` with TTL 48h.

| Cap | Value | Bucket |
|---|---|---|
| Total XP awarded per UTC day | 500 XP | `total` |
| XP from text quick-logs per day | 150 XP | `text` |
| XP from photo logs per day | 200 XP | `photo` |
| XP from weight logs per day | 30 XP | `weight` |
| Food logs per meal slot (breakfast/lunch/dinner/snack) per day | 3 | enforced in tracking use case |
| Photo logs per hour | 30 (existing, ADR-0021 rate-limit) | reused |
| Weight logs per day | 3 | enforced in tracking use case |
| Min interval between weight logs | 30 min | sliding |
| Weight delta sanity | abs(delta_kg) ≤ 2.0 kg/day OR ≤ 5 % bodyweight | reject log, no XP |

Photo SHA256 cross-user dedup already exists (ADR-0021 Layer 1). Extension: **same-user same-SHA256 within 24h awards XP only on first occurrence**. Stored in existing `vision_jobs.image_sha256` index.

Region pinning: `country` claimed at profile creation is **immutable for 30 days**. Change requires explicit endpoint + writes to `profile_region_change_audit` (append-only). Leaderboard reads `country` from profile, never from request.

Streak boundary: streak day computation uses **profile `tz`** (already stored), and increments require **≥ 20 h since previous streak-eligible log**. This kills the 23:59→00:01 chain without harming legitimate late-night users.

### Layer 2 — Anomaly heuristics (async worker, Arq)

Job `gamification.anti_cheat_score` runs nightly per user with ≥1 log that day. Pure deterministic features, scored 0..100. Findings persisted to Postgres `leaderboard_audit` (append-only).

Signals:

- **Log timing entropy** — Shannon entropy of hour-of-day distribution over last 14 days; bot-like uniformity flags.
- **Photo similarity cluster** — perceptual hash (pHash, 64-bit) Hamming distance ≤ 5 against same user's last 30 photos; flag if >40 % are near-duplicates. pHash computed inside existing vision worker, stored alongside SHA256.
- **Macro impossibility** — daily kcal sum vs profile TDEE × 3 → flag (one user logging 7000 kcal/day repeatedly is either a bug or farming).
- **Weight trajectory vs logs** — if user logs steep weight loss while logging >TDEE intake (or vice versa), flag.
- **Social graph density** — count of mutual follows + cheers among accounts created within 7 days of each other on same IP `/24` or same device fingerprint hash; >3 ⇒ collusion suspect.
- **Account age vs rank** — top-10 placement with account age < 7 days ⇒ probation flag.

Score ≥ 70 ⇒ shadow-ban (Layer 3). Score 40–69 ⇒ visible warning row in owner dashboard (Postgres view), no user-facing action.

### Layer 3 — Shadow-ban + manual review

Shadow-ban = user's XP keeps accruing in their own profile (no visible signal to them) but their entry is **excluded from `ZADD` into the leaderboard sorted set**. Stored as `gamification_shadow_ban (user_id, reason, score, created_at, lifted_at NULLABLE)`.

Owner reviews `leaderboard_audit` weekly. Lift via single SQL update. No appeals endpoint in closed-beta; complaints route to owner email.

### Where each check lives

| Check | Layer | Location |
|---|---|---|
| XP daily caps | 1 | `app/gamification/application/award_xp.py` (use case, Redis INCR) |
| Per-meal-slot food-log cap | 1 | `app/tracking/application/log_food.py` |
| Weight delta sanity | 1 | `app/tracking/application/log_weight.py` |
| Photo per-hour rate limit | 1 | `app/vision/presentation/rate_limit.py` (existing) |
| Same-SHA256 XP suppression | 1 | `award_xp` use case reads `vision_jobs.image_sha256` |
| Region immutability | 1 | `app/profile/application/update_profile.py` |
| Streak 20h minimum | 1 | `app/gamification/application/update_streak.py` |
| pHash compute | 2 | `app/vision/infrastructure/vision_worker.py` (extension) |
| Nightly anomaly scoring | 2 | Arq job `gamification.anti_cheat_score` |
| Shadow-ban write | 3 | Arq job → Postgres |
| Leaderboard ZADD skip | 3 | `app/gamification/application/award_xp.py` reads shadow-ban set (cached in Redis with 60s TTL) |

### Storage

- **Redis** — XP counters, rate limits, shadow-ban set cache (`gami:shadowban` → SET of user_ids, refreshed 60s).
- **Postgres** — `leaderboard_audit` (append-only, anomaly scores per user per day), `gamification_shadow_ban` (current state), `profile_region_change_audit`. All within existing migration discipline (ADR + reversible).
- **Vision worker** — adds `phash_64` column to `vision_jobs`. Migration is additive nullable; no backfill.

## Feature flag rollout plan

Master flag `leaderboard_enabled` stays **OFF** until **all** of:

1. Layer 1 caps shipped + unit tests + property-based test on cap arithmetic.
2. `gamification_shadow_ban` table + migration deployed.
3. `leaderboard_audit` table + migration deployed.
4. Nightly Arq job registered and observed running for ≥ 7 days in production with zero errors (worker logs clean, scores written).
5. Owner-side SQL view `leaderboard_audit_dashboard` exists (no UI; raw SQL is fine for closed-beta).
6. Manual abuse drill: owner creates 2 sock-puppet accounts on staging, runs farming scripts, confirms caps + shadow-ban path triggers within one anomaly cycle.
7. ErrorTracker captures `gamification.anti_cheat_score` job failure (admin endpoint `/admin/errors/recent`).

Once flipped ON for closed-beta:

- Country whitelist hardcoded to active beta regions (MX, AR, CL, PE, CO). Other countries return `{ "enabled": true, "rows": [] }`.
- Period whitelist: `week` only (no all-time until ≥ 30 days of audit data exists).
- Top-50 cap on returned rows (existing `limit ≤ 100` reduced).

## Out of scope (closed-beta)

- ML-based fraud scoring (no labelled data, no training pipeline budget).
- CAPTCHA / hCaptcha (UX friction unwarranted at ≤100 users).
- Device-attestation (App Attest / Play Integrity) — deferred to post-mobile-launch ADR.
- IP geolocation as primary region source — kept as secondary signal only inside Layer 2 social-graph heuristic.
- Per-user appeals API — owner-mediated only.
- Real-time anomaly detection — nightly batch is sufficient at this scale.

## Consequences

### Positive

- Deterministic, auditable, cheap. Total infra cost: zero new services.
- Each layer independently flag-gated; partial rollback is one SQL UPDATE.
- Audit log is append-only Postgres — replayable, exportable, GDPR-friendly (ADR-0005 erasure honoured by `user_id` cascade).
- Caps double as cost protection for downstream (TDEE recalibration, vision spend).

### Negative

- Legitimate power users (true >300 XP/day) clipped by daily cap until cap is widened post-beta. Mitigated by 500 XP/day headroom (≈ 10 logs + 2 photos + streak bonus).
- pHash adds ~5 ms per photo job; trivial vs existing OpenAI call.
- Nightly job introduces a new failure mode (job dies silently). Mitigated by ErrorTracker capture + flag-7 in rollout plan.
- Shadow-ban without user notice has ethical surface — acceptable in closed-beta with explicit ToS clause, must revisit at GA.

### Risk accepted

- Determined adversary with rotated IPs and varied photos defeats Layer 2. Acceptable at closed-beta scale; revisit with ML when ≥ 1000 MAU.
- pHash false positives on legitimately-similar meals (daily oatmeal). Mitigated by score threshold (40 % of last 30) and Layer-3 manual review.

## Rollback

- `leaderboard_enabled = false` in `feature_flags` — endpoint returns empty rows instantly, no redeploy.
- Per-layer sub-flags (`leaderboard_caps_enabled`, `leaderboard_anomaly_enabled`, `leaderboard_shadowban_enabled`) — independently revocable.
- Migrations are additive; rollback = flip flags + leave tables in place.

## References

- Code: `app/gamification/presentation/router.py:70-89`, `app/gamification/application/`, `app/vision/infrastructure/`
- Related ADRs: ADR-0004 (cost cap), ADR-0005 (GDPR erasure), ADR-0021 (vision pipeline — SHA256 dedup reused), ADR-0017 (legal scope)
- PROJECT_STATE blocker: "Anti-cheat for leaderboard gated behind feature flag"
- Industry reference: Strava segment leaderboards (caps + shadow-flag), Duolingo league shadow-ban model
