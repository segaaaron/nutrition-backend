# pgvector Tenancy Model

**Audit date:** 2026-06-01
**OWASP coverage:** API1 (Broken Object Level Authorization) — vector flavour
**Owner:** Security Lead

---

## TL;DR

All pgvector queries in NOVA are correctly tenant-isolated or read from
explicitly global catalogs. **Zero leak paths identified at audit time.**

---

## Table classification

| Table | Has `embedding` column | Tenancy | Filter required? |
|-------|------------------------|---------|------------------|
| `recipes` | Yes (1536-dim) | **GLOBAL catalog** | NO — every user sees same catalog |
| `foods` | Yes (1536-dim) | **GLOBAL catalog** | NO — every user sees same catalog |
| `coach_faq` | Yes (1536-dim) | **GLOBAL catalog** | NO — canned coach answers shared |
| `vision_personal_cache` (food_matcher) | No (text-only) | Per-user | YES (already filters by `user_id`) |
| `plans`, `plan_meals` | No (embedding lookup is via JOIN to recipes) | Per-user | YES (already filters by `user_id` on plans) |
| `taste_profile` (computed) | Vector stored per user | Per-user | YES (always WHERE user_id) |

---

## Vector query inventory + filter status

| File | Query intent | Filter check |
|------|--------------|--------------|
| `app/recipes/infrastructure/repositories.py:139,206` | Hybrid trigram + cosine on recipes catalog | ✅ Global catalog — no user filter needed |
| `app/recipes/infrastructure/repositories.py:257` | Food catalog cosine | ✅ Global catalog |
| `app/vision/infrastructure/food_matcher.py:60` | Personal food cache lookup | ✅ `WHERE user_id = :uid` |
| `app/vision/infrastructure/food_matcher.py:72,93` | Foods catalog match | ✅ Global catalog |
| `app/plan/application/layer3_ranking.py:64` | Recipes catalog rank | ✅ Global catalog |
| `app/plan/infrastructure/taste_fetcher.py:21,45` | User taste vector centroid | ✅ `WHERE p.user_id = :uid` |
| `app/coach/application/propose_swap.py:34,44-48` | Swap candidates | ✅ Plan ownership verified, recipes global |

**Verdict:** 7 unique vector query sites; all classified correctly.

---

## Threat model

### What a leak would look like

Hypothetical bug: a new endpoint exposes embeddings of a per-user vector
(e.g. taste profile) without filtering by `user_id`. User A queries the
endpoint with user B's UUID and obtains user B's preference fingerprint
→ behavioural inference attack (PII-adjacent).

### Why this doesn't happen today

1. **Catalog vs per-user separation is structural.** `recipes` and `foods`
   have no `user_id` column. Per-user vector data (`taste_profile`,
   `personal_cache`) is computed/joined from tables that DO have
   `user_id`, and every query filters by it.

2. **BOLA helper `assert_owns()` covers id-based access.** Even if
   embeddings were exposed in a future endpoint, BOLA check would
   reject cross-user access by ID.

3. **No `/embeddings/{user_id}` style endpoint exists.** Embeddings are
   internal computation, never serialised to client.

---

## Regression guard

`tests/unit/test_pgvector_tenancy_audit.py` is a static-analysis test that
fails if a new table with an `embedding` column lacks either:
- A `user_id` column (per-user tenancy), OR
- An explicit entry in the `GLOBAL_CATALOG_TABLES` allowlist.

Forces any new vector model to be classified explicitly. Prevents
"forgot to filter" bugs at PR time.

---

## Procedure when adding a new vector model

1. **Decide tenancy**: global catalog or per-user?
2. **If global**: add table name to `GLOBAL_CATALOG_TABLES` allowlist in
   `tests/unit/test_pgvector_tenancy_audit.py`. Document rationale in
   the migration that creates it.
3. **If per-user**: add `user_id UUID NOT NULL` column + FK to `users`.
   Every query MUST include `WHERE user_id = :uid`.
4. **Either way**: add unit test asserting the tenancy classification.

---

## Next review

This document is reviewed:
- On every migration that adds an `embedding` column
- Quarterly as part of security review cycle
- After any incident touching plan/coach/vision modules

---

## Related

- OWASP API Security Top 10 (2023) — API1: Broken Object Level Authorization
- ISO 27001 Annex A — A.9.4 (Information Access Restriction)
- ADR-0008 (multi-region catalog) — clarifies recipes/foods global status
