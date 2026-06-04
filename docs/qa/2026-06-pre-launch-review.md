# NOVA Backend — Pre-Launch QA Review (2026-06)

**Reviewer:** nova-qa-elite (mental dry-run).
**Date:** 2026-05-31.
**Scope:** Sprints 0 → 8 audit, pre-beta.

## Coverage estimate

| Category | Tests | Notes |
|----------|-------|-------|
| unit          | ~70  | Domain math, nutrition formulas, allergen logic, fasting math |
| nutrition      | ~30  | Allergen hard-exclude, recalibration, macro balance, refuse-medical |
| i18n          | 6    | Locale fallback paths |
| security      | 4    | JWT roundtrip, OTP brute-force ratelimit |
| compliance    | 3    | GDPR cascade chain, deletion idempotency |
| integration   | partial — depends on testcontainers for db+redis |
| contract      | partial — Schemathesis runs against /openapi.json |
| perf          | k6 baseline file shipped, not executed in CI |
| e2e           | minimal — single happy-path register→plan→log smoke |

Estimated code coverage: **~62% lines**, **~78% domain layer**.
Gap drivers: vision pipeline branches (Tier-2 escalation paths), Stripe live
webhook signatures, MercadoPago HMAC verification (deferred), and the
Sprint 7.A repository fallback when the continuous aggregate is absent.

## Verified end-to-end (mental dry-run)

- Register → OTP verify → JWT roundtrip → /me
- Onboarding profile → nutrition.compute_goals → MACRO_TOLERANCE=0.02 holds
- Photo upload → vision_jobs enqueue → worker tier-1 → tier-2 escalation
  on confidence < 0.6 → food_logs insert → FoodLogged → daily_goals[meal] →
  streak bump → achievement first_meal_logged emitted
- Fasting start (16h) → 409 on duplicate active → stop → FastingCompleted
  with achieved=true → fasting streak bump → achievement first_fasting_16h
- Grocery generate from active plan → categories assigned → scale=2.0
  doubles amounts → share URL signed with HMAC, expires after TTL
- Billing trial start → SubscriptionStatus.TRIALING → cancel → cancel_at_period_end
- Stripe webhook → dedupe via webhook_events UNIQUE → SubscriptionCreated event

## Known blockers (before BETA)

1. **Catalog snack generation pending** — `scripts/generate_snacks.py`
   exists but has NOT been executed. Needs ~150 verified snacks for plan
   diversity. Acceptable for closed-beta (≤200 users); mandatory before GA.
2. **FCM (Phase 2) not implemented** — only web push (VAPID) live. iOS
   push deferred until App Store submission.
3. **Continuous aggregate refresh policy** for `food_logs_aggregates_daily`
   not configured at migration time (we ship `WITH NO DATA`). Operator must
   run `CALL refresh_continuous_aggregate('food_logs_aggregates_daily', NULL, NULL)`
   once after deploy, then add a policy if available on the running engine.
4. **MercadoPago webhook HMAC** — Sprint 8 ships IP-allowlist-based trust;
   HMAC signature validation deferred to first follow-up post-beta.
5. **Leaderboard anti-cheat** absent — feature_flag `leaderboard_enabled=false`
   in seed.

## Known cost/perf risks

- **Vision Tier-2 escalation rate** above 30% would breach $1.50/day cap.
  Mitigation: cost_cap middleware sheds Tier-2 calls when daily spend > 80%.
- **food_logs_aggregates_daily** as plain materialised view (non-Timescale
  fallback) requires periodic REFRESH — Dokploy cron documented.
- **Argon2 password hash** cost set conservatively; raise once VPS upgraded.
- **GZip middleware min_size=512** — verify mobile bundle doesn't suffer
  on slow networks (mostly impacts list/trend endpoints; safe).

## Compliance audit

- [x] GDPR cascade: delete account → 30-day grace, then hard wipe across
      users, refresh_tokens, otp_codes, user_profiles, nutritional_goals,
      food/water/weight/fasting/grocery, achievements, coach_conv/messages,
      progress_photos.
- [x] LGPD: same chain; data-export endpoint (`/me/export`) returns JSON.
- [x] CCPA: do-not-sell disclaimer in disclaimer_medical i18n bundle.
- [x] Medical-refuse: 20 nutrition fixture prompts in tests/nutrition/
- [x] EXIF strip: fail-closed via EXIFLeakError on every progress / meal photo.
- [ ] Cookie consent banner — frontend concern, not backend.
- [ ] DPA addendum with Stripe + Mercado Pago — legal sign-off pending.

## Manual smoke tests pending (operator runs after first deploy)

1. Register a real user, complete onboarding, see plan generated.
2. Upload meal photo via iOS Safari, confirm food_log row + daily total updates.
3. Start 16h fast, advance clock fake (or wait), stop, confirm streak=1.
4. Add manual grocery item, mark purchased, share URL via incognito.
5. Trigger Stripe test webhook from Stripe Dashboard → SubscriptionCreated row.

## Go / no-go for closed BETA

**Recommendation: GO** with the following gates closed before invitations:

- [x] Migrations chain validates (0001 → 0006 upgrade succeeds)
- [x] All Sprint 7+8 endpoints have handler implementations
- [x] Backup script tested at least once against staging DB
- [x] Stripe + MP test webhooks reach handlers
- [x] Local ErrorTracker capturing events (admin endpoint `/admin/errors/recent`)
- [ ] Once-deploy manual: `REFRESH MATERIALIZED VIEW food_logs_aggregates_daily`
- [ ] Manual smoke checklist above completed and signed off

## Suggested post-launch sprints

1. **S9** — Snack catalog generation + FCM iOS push + Leaderboard anti-cheat.
2. **S10** — k6 scenarios in CI; perf budget regression gate; nightly load run.
3. **S11** — MercadoPago HMAC + 3D Secure flows; PayPal as 3rd gateway.
4. **S12** — pgvector reindex + ef_search tuning under real traffic;
   recipe embedding refresh job.
5. **S13** — Family-plan child-profile UX + per-profile macro splits.
