# 🌙 Session Handoff — 2026-06-01 night

**For:** Next session (Miguel resumes work tomorrow)
**Status:** Sleeping. Resume here.
**Last commit:** `4dd4dc1` on main

---

## Where we left off

Sprint S0 + S1-quick shipped. ErrorTracker local replaced Sentry. Team docs + RBAC + BACKLOG + STATUS all committed. Two coordinated agent audits (`nova-clinical-nutrition-generator` + `nova-nutrition-algorithms-expert` persona) finished pre-prod analysis of nutrition catalog + algorithms.

Detailed reports:
- `docs/algorithms/CATALOG_AUDIT.md` — 2000 recipes nutrition audit (265 LoC)
- `docs/algorithms/PRE_PROD_AUDIT.md` — math + algorithms gaps (312 LoC)
- `docs/security/STATUS.md` — full security posture
- `docs/security/BACKLOG.md` — S1/S2/S3 deferred with triggers
- `docs/team/TEAM.md` — 10-agent team map
- `CLAUDE.md` — golden rule team-only

---

## 🚨 Top 3 things to know on resume

### 1. HARD BLOCKER — 4017 enum violations in catalog

JSON `data/meals/nova_meals_catalog.cleaned.json` uses legacy enum values
(`maintain_weight`, `build_muscle`, `gain_weight`, `general_health`,
`moderate`, `active`). Postgres enums won't accept these → DB seed fails.

**Fix:** scripted remap before seed (1h work):
```python
{
    "maintain_weight": "maintain",
    "build_muscle": "muscle_gain",
    "gain_weight": "weight_gain",
    "general_health": "health",
    "moderate": "moderately_active",
    "active": "very_active",
}
```

### 2. SAFETY — 2 critical nutrition/legal issues

**Tree-nut allergen leak (37 recipes):**
- Recipes with almond/walnut/cashew/pistachio/etc in `ingredients[]`
  but missing `tree_nuts` in `allergens[]`
- Anaphylaxis risk = lawsuit + FALCPA + EU 1169 violation + App Store reject
- **Mitigation today (1h):** add defensive regex in `app/plan/application/layer1_eligibility.py`
  that scans `ingredients[]` for nut keywords regardless of allergens array
- **Fix catalog (2h):** patch 37 entries (nutrition-generator agent task)

**Diabetes_t2 high-carb tagging (87 recipes):**
- Marked `recommendedForConditions: ["diabetes_t2"]` with carbs > 60g/meal
- Glycemic spike medical risk
- Fix: either re-tag without diabetes_t2 OR compute GI+GL and gate by GL<10

### 3. Gate-block 5 user segments at signup tonight

Feature flag refuse during onboarding until catalog + algorithms ready:

```
Refuse signup if:
- conditions ∋ diabetes_t1
- conditions ∋ diabetes_t2
- conditions ∋ pregnancy
- conditions ∋ lactation
- conditions ∋ ckd
- region == us
```

**Reason:** algorithms don't have catalog data nor macro overrides.
Without gate, a hypertensive user can receive a 1200mg-sodium recipe
silently (L1 SQL filter pass-through on NULL fields).

Effort: 1h.

---

## 🟡 Quick win to apply on resume

**Backfill OpenAI embeddings for 2000 recipes: ~$0.40 + 30min**

L3 ranking weights `cosine(taste_vector, recipe.embedding)` at 0.40.
Today: zero recipes have embeddings → 40% of scoring is dead weight.

Single script run = biggest quality jump for $0.40 of OpenAI calls.

Command sketch:
```bash
python scripts/compute_embeddings.py --table recipes --batch 50
```

(check `scripts/compute_embeddings.py` — already exists, see if it iterates the catalog)

---

## 📋 Decision pending

**Ship MVP narrow vs full?**

| Option | Effort | Coverage | Risk |
|--------|--------|----------|------|
| **A) Ship narrow this week** | 8h | LatAm omnivore + 3 goals + no declared conditions | Zero medical/legal risk |
| **B) Ship full in 1-2 weeks** | 25h | + diabetes/CKD/preg/lactation + US region | Catalog must be patched first |

My recommendation: **A**. Validate hypothesis with safe segment. Expand when you have real user data.

---

## ✅ What's already shipped (main = `4dd4dc1`)

### Security (Sprint S0 + S1-quick)
- BOLA assert_owns
- BOPLA Pydantic extra=forbid
- JWT pyjwt + Redis denylist + kid rotation
- MercadoPago HMAC strict
- Idempotency Redis+DB
- Security headers + CORS + /docs gate
- AntiSniff Proxyman/Charles defense
- SSRF guard outbound httpx
- Per-IP rate-limit
- pgvector tenancy audit + regression
- Coach guardrails expanded (medical + offtopic + injection)
- SECURITY.md + VDP
- RBAC matrix (Role enum + require_role dep)
- MIME sniff magic bytes vision
- Anomaly guard weight tracking
- CI scans (bandit + semgrep + gitleaks + pip-audit + trivy + dependabot)
- ErrorTracker local (replaced Sentry SaaS)

### Team / Process
- 10 agents in `.claude/agents/`
- CLAUDE.md golden rule team-only
- docs/team/TEAM.md responsibility matrix
- docs/security/STATUS.md defense matrix

### What's deferred to BACKLOG
- S1 remaining (5 items) — triggers documented
- S2 (8 items) — triggers documented
- S3 (7 items) — triggers documented
- Declined paid: Sentry SaaS, Pen-test, B2 backup off-site
- Mobile crashes → Firebase Crashlytics (mobile team)

---

## 🎯 Mañana — first 90 minutes prioridad

Si tienes 90 min y quieres ship Option A:

```
[15min] Read this file + CATALOG_AUDIT.md + PRE_PROD_AUDIT.md
[15min] Decide A vs B
[60min] Execute Option A:
        1. Enum remap script (10min) + run on cleaned.json
        2. Tree-nut defensive regex in layer1_eligibility.py (15min)
        3. Gate 5 segments in identity signup (15min)
        4. Embeddings backfill (sets up + run, 20min)
```

After 90min you have a safe-to-ship MVP narrow slice.

---

## 🔄 Continuation triggers for agents

When you resume and dispatch agents:

**To nutrition-generator:**
- "Patch the 37 tree-nut recipes — add `tree_nuts` to allergens[]"
- "Patch the 87 diabetes_t2 high-carb recipes — re-tag or remove diabetes_t2"
- "Generate 50 snacks for LatAm/omnivore covering 3 goals"

**To algorithms-expert (use general-purpose with persona until session reloads .claude/agents/):**
- "Implement condition macro overrides for diabetes_t2 (GL<100/day, fiber>=25g, carbs<45%)"
- "Implement Cunningham BMR fallback when bodyfat_pct present"
- "Compute glycemic load on top of recipe.carbs_g if GI available"

**To qa-elite:**
- "Build golden set of 30 user profiles (athlete, sedentary, vegan, elderly, etc) for plan generation regression testing"

**To architect:**
- "Add migration for micronutrient columns (gi, fiber_g, sodium_mg, potassium_mg, phosphorus_mg, iron_mg, heme_pct, calcium_mg, omega3_mg) on recipes table"

---

## 💤 Buenas noches

42 commits shipped in this session. Worktree + main in sync. Tests
all green (~190 new). Zero monetary cost added. Zero paid SaaS deps.

Repo state: ready to deploy narrow MVP after ~8h tomorrow work.

Tomorrow you decide ship strategy. See you on resume.
