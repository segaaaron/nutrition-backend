# NOVA Pricing — Freemium + Photo Tier Strategy

> **Last updated:** 2026-06-04
> **Status:** Decided by owner. Re-evaluate at 1,000 paying users.
> **Strategy:** LatAm-first undercut vs Fitia (33-50% cheaper).

---

## Pricing tiers

| Tier | Price (USD) | Billing | Target audience | Notes |
|------|-------------|---------|-----------------|-------|
| **Free** | $0 | — | Acquisition / top of funnel | Plan generation básico, text quick-log unlimited, **0 photos**, sin coach SSE |
| **Premium Monthly** | $9.99 | per month | Casual paying users | Photos sin límite (cost cap), coach SSE, recalibration |
| **Premium Yearly** | $39.99 | per year (~$3.33/mo) | Committed users | Same as monthly, 67% discount vs monthly cadence |
| **Family Yearly** | $59.99 | per year | Households (≤4 users) | Shared catalog + isolated plans per member |

### Fitia benchmark (reference competitor)

| Plan | Fitia | NOVA | Discount |
|------|-------|------|----------|
| Monthly | $19.99 | $9.99 | **50% undercut** |
| Yearly | $59.99 | $39.99 | **33% undercut** |
| Family Yearly | $89.99 | $59.99 | **33% undercut** |

---

## Photo tier strategy

| Phase | Photos/day | Cost (per ADR-0004) |
|-------|------------|---------------------|
| **Free (post-trial)** | 0 | $0 — text quick-log only |
| **Trial (first 7 days post-signup)** | 3/day | ~$0.022/user/day × 3 × 7 = **~$0.46/user trial total** |
| **Premium (paid)** | Unlimited (soft) | Hard cap **$1.50/user/day** (ADR-0004) |

### Trial rationale
- Vision pipeline is NOVA's differentiator → free users must taste it.
- Cost ceiling per trial user $0.46 → conversion rate >2% pays the cost.
- Post-trial without upgrade → silent revert to free tier (text-only).

### Photo prefilter (CLAUDE.md scope rule)
ACCEPT: ready-to-consume food + ≥20 kcal estimated.
REJECT: supplements, pills, powders, plain water, black coffee, plain tea, non-food, empty plates.
Rejected photos do **not** count against trial quota.

---

## Currency conversion

### Stripe (USD direct, no conversion at checkout)
- USA, EU, Canada, UK, Australia → charged USD.

### MercadoPago (auto-converts to local currency)
| Country | Currency | Notes |
|---------|----------|-------|
| Peru | PEN | Primary launch market |
| Mexico | MXN | Largest LatAm TAM |
| Colombia | COP | |
| Chile | CLP | |
| Argentina | ARS | High inflation — review quarterly |
| Brazil | BRL | Future (Portuguese localization pending) |
| Uruguay | UYU | |

MercadoPago handles FX at processing time. Backend stores price in USD canonical; checkout layer applies local conversion.

---

## Conversion economics

### Assumptions (closed-beta baseline)
- Trial → Premium conversion target: **3%** (industry baseline 2-5% for freemium SaaS).
- Premium Monthly LTV (12-month horizon): $9.99 × 6 avg retained months = **~$60**.
- Premium Yearly LTV: $39.99 × 1.4 renewal factor = **~$56**.
- Variable cost per premium user/month: ~$0.66 (avg $0.022/day × 30) well below $1.50 hard cap.
- **Contribution margin per paying user:** ~85% gross.

### Trial cost coverage math
- 100 trial signups × $0.46 = $46 vision spend.
- Required converters at $9.99/mo to break even on month 1: **5 users (5%)**.
- Below 3% conversion → trial economics turn negative → trigger re-evaluation.

---

## Re-evaluation triggers

Revisit this document when **any** of the following occurs:

1. **1,000 paying users reached** → market-test +20% price increase on new signups (A/B).
2. **Trial conversion <2%** sustained over 30 days → shorten trial to 3 days OR reduce photos/day to 2.
3. **OpenAI vision pricing changes ±25%** → adjust photo trial quota or hard cap.
4. **Fitia changes pricing** → re-baseline undercut.
5. **First $10k MRR** → introduce annual-only "Pro" tier at $79.99 with priority coach SSE.

---

## Cross-references

- Cost cap enforcement: `docs/adr/0004-openai-cost-cap.md`
- Billing context implementation: `app/billing/`
- MercadoPago webhook hardening: `docs/security/PLAN.md`
- Meal planning strategy: `docs/product/2026-05-30-meal-planning-strategy.md`
