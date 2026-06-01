# Onboarding Form Audit + Catalog Liquid Expansion — Team Synthesis

**Date:** 2026-06-01
**Authors:** nova-nutrition-algorithms-expert + nova-clinical-nutrition-generator (coordinated)
**Scope:** iOS onboarding form (single screen) → backend plan generation safety
**Status:** Recommendations — pending owner approval

---

## TL;DR

Form covers ~85% of safe-plan inputs. 2 P0 fixes block ship:
1. **Add `dietary_pattern` field** (omnivore/pescatarian/vegetarian/vegan) — without this, vegan users get meat plans.
2. **Refuse plan if `allergens_freetext` non-empty** — Layer1 cannot match free strings; silent allergen exposure = anaphylaxis.

Plus 2 P1 clarifications, 1 ADR (sex-at-birth vs gender), and 30 liquid recipes (juices + smoothies + viral mixes) ready for batch generation.

Catalog needs **3 additive fields** (no breaks): `dietary_pattern`, `cuisine_region[]`, `meal_format`. No `meal_times_4` enum change — liquid recipes fit `breakfast/snack` slots; format axis lives in `meal_format`.

---

## 1. Form field → algorithm input map

| Form field (iOS) | Server field | Algorithm consumer | Status |
|---|---|---|---|
| Nombre completo | `full_name` | display only | OK |
| Edad | `age: int` | Mifflin BMR | OK with bounds 18-80 |
| Sexo (Hombre/Mujer) | `sex_at_birth: Literal["male","female"]` | Mifflin, LBM fallback | OK — **rename internal** |
| Unidades kg·cm / lb·ft | display preference | none | OK |
| Peso (kg) | `weight_kg: Decimal` | BMR, protein, fat targets | OK — bounds 30-250 |
| Talla (m) e.g. 1.75 | `height_m: Decimal` → `height_cm = ×100` | Mifflin BMR | OK — bounds 1.20-2.40 m |
| Objetivo (5 buttons) | `goal: Goal` | kcal adjust, fat fraction, protein k | OK |
| Nivel de actividad (5 levels) | `activity_level: ActivityLevel` | TDEE multiplier | OK + auto-derive `athletic` if `extra_active` |
| Condición médica (multi) | `conditions: list[Condition]` | Layer1 clinical gates | OK enum subset, **"Otros…" decoupled** |
| Alergias (multi) | `allergens: list[Allergen]` | Layer1 hard exclude | OK enum, **"Otra alergia…" P0 BLOCK** |
| (missing) | `dietary_pattern: DietaryPattern` | Catalog filter | **P0 ADD** |
| (missing) | `region: Region` | Catalog `regions[]` filter | OK auto-derive from `Accept-Language` |
| (missing) | `meals_per_day: int` | Macro distribution per slot | OK fallback 3 + warn |
| (missing) | `bodyfat_pct: Decimal?` | Cunningham BMR for athletes | OK fallback Mifflin |
| (missing) | `prep_time_max: int?` | Ranking signal | OK fallback 30min |

---

## 2. P0 issues — block ship

### P0.1 — Free-text allergen silent exposure

`"Otra alergia…"` UI button accepts free text. Layer1 SQL matches against closed enum array `recipe.allergens[]`. A free string never matches → user with `"ajonjolí"` (sesame) allergy receives sesame recipes silently.

**Decision:** if `allergens_freetext` non-empty AND non-whitespace, refuse plan generation with `urn:nova:problem:plan:allergen-unmapped-requires-review` (422). UI shows: "Tu alergia personalizada requiere revisión manual. Contacta soporte para activar tu plan." Owner triage queue: map to existing enum OR escalate to ADR for vocab expansion.

**Never silently ignore an allergen.**

### P0.2 — Missing `dietary_pattern` defaults dangerously

Form does not ask omnivore/vegetarian/vegan. Catalog filters by `dietary_pattern`. Defaulting to `omnivore` silently → vegan user receives 80% irrelevant + ethically harmful recipes.

**Decision:** add single chip row to onboarding form between Objetivo and Actividad:

```
DIETA
[ 🍖 Omnívoro ] [ 🐟 Pescetariano ] [ 🥗 Vegetariano ] [ 🌱 Vegano ]
```

Mandatory single-select. No "Otros" — extend enum later via ADR (kosher/halal/keto/mediterranean H2 scope).

---

## 3. P1 issues — fix this sprint

### P1.1 — "Talla (M)" label ambiguous

UI label "TALLA (M)" with value `1.75` reads as meters but `M` could be misread (Mediana / Maximum). Backend enforces meters via Pydantic `height_m ∈ [1.20, 2.40]`; values like `175` (cm by mistake) rejected.

**Decision:** UI label change → `"Estatura (m, ej. 1.75)"`. Backend rejects out-of-range with `urn:nova:problem:plan:invalid-height` (422).

### P1.2 — Athlete BMR Mifflin underestimates

`activity_level == "extra_active"` athletes with low body fat get BMR underestimated 5-10% by Mifflin (which assumes population-mean FFM). Cunningham (`500 + 22·LBM`) is more accurate but needs `bodyfat_pct`.

**Decision:** if `activity_level == extra_active`, append optional step 2 question (after first plan rendered): "¿Conoces tu % de grasa corporal?" — optional, skip → declared fallback `bmr_formula=mifflin_no_bodyfat`.

### P1.3 — "Otros…" condition free text

Layer1 routes only known conditions to clinical gates. "Otros…" cannot be safely routed (NLP mapping is H2 scope).

**Decision:** persist as `conditions_freetext` (encrypted PII column). Surface in coach LLM context only with explicit consent flag. Do NOT pass to Layer1. Surface warning `unmapped_condition_ignored_for_plan` in profile.

### P1.4 — Condition label mapping

| Form chip | Server enum | Notes |
|---|---|---|
| Diabetes tipo 2 | `diabetes_t2` | OK |
| Hipertensión | `hypertension` | OK |
| **Celiaquía** | **`celiac` AND `gluten`** | Write BOTH — condition + allergen filter |
| **Colesterol alto** | **`dyslipidemia`** | NOT `hypercholesterolemia` (lab-confirmed only) |
| Hipotiroidismo | `hypothyroidism` | OK |
| Otros… | `conditions_freetext` (PII column, not filter) | See P1.3 |
| Ninguna | `[]` (empty) | sentinel handling |

---

## 4. Pydantic schema (canonical)

```python
# app/profile/presentation/schemas.py (extend existing)
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Sex = Literal["male", "female"]
Goal = Literal["weight_loss", "maintain", "muscle_gain", "weight_gain", "health"]
Activity = Literal["sedentary", "lightly_active", "moderately_active", "very_active", "extra_active"]
Condition = Literal[
    "diabetes_t2", "hypertension", "celiac", "dyslipidemia", "hypothyroidism",
]
Allergen = Literal[
    "dairy", "gluten", "tree_nuts", "shellfish", "egg", "soy",
]
DietaryPattern = Literal["omnivore", "pescatarian", "vegetarian", "vegan"]

class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")

class OnboardingRequest(_Strict):
    full_name: str = Field(min_length=1, max_length=120)
    age: int = Field(ge=18, le=80)
    sex_at_birth: Sex = Field(json_schema_extra={"example": "male"})
    weight_kg: Decimal = Field(ge=Decimal("30"), le=Decimal("250"))
    height_m: Decimal = Field(ge=Decimal("1.20"), le=Decimal("2.40"))
    goal: Goal
    activity_level: Activity
    dietary_pattern: DietaryPattern  # P0 add
    conditions: list[Condition] = Field(default_factory=list, max_length=6)
    conditions_freetext: str | None = Field(default=None, max_length=200)
    allergens: list[Allergen] = Field(default_factory=list, max_length=7)
    allergens_freetext: str | None = Field(default=None, max_length=200)
    units_display: Literal["metric", "imperial"] = "metric"

    @property
    def height_cm(self) -> Decimal:
        return self.height_m * Decimal("100")

    @model_validator(mode="after")
    def reject_unmapped_allergen(self) -> "OnboardingRequest":
        if self.allergens_freetext and self.allergens_freetext.strip():
            raise ValueError("allergen_unmapped_requires_review")
        return self
```

Age <18 → `pediatric_outside_mvp_scope`. Age >80 → `geriatric_requires_clinical_review`. Both block (segment gate).

---

## 5. Catalog schema changes (additive, non-breaking)

Three new fields in `matchingCriteria` (defaultable, no rewrite of 2000 existing):

| Field | Type | Default existing | New recipes |
|-------|------|------------------|-------------|
| `dietary_pattern` | enum | `omnivore` | required at gen-time |
| `cuisine_region` | list[enum] | `[per-recipe inferred]` | required |
| `meal_format` | enum | `solid` | required |

Enum values:
- `dietary_pattern`: `omnivore, pescatarian, vegetarian, vegan` (H2 extends: kosher, halal, ketogenic, mediterranean, DASH, low_FODMAP)
- `cuisine_region`: `latam, mediterranean, asian, middle_eastern, north_american, nordic, african, fusion`
- `meal_format`: `solid, semi_solid, liquid`

Migration 0010 (TBD): adds columns + defaults + GIN on `dietary_pattern`. Reversible.

**`meal_times_4` enum STAYS unchanged.** Liquid recipes use `meal_format` for differentiation. ADR-0001 intact.

---

## 6. Liquid expansion (jugos + smoothies + viral mixes)

### Design decisions

- 30 new liquid recipes initial batch. Slot in `breakfast` or `snack`.
- `meal_format: liquid | semi_solid`
- `tags[]` open list — controlled at catalog-gen time:
  ```
  liquid_meal, smoothie, juice, viral, pre_workout, post_workout,
  overnight_prep, no_cook, high_satiety_liquid, functional_beverage
  ```

### Hard catalog-gen validators (block INSERT)

1. **Sugar cap:** liquid recipe with `carbsG > 35` from added fruit → `recommendedForConditions` cannot include diabetes_t1/diabetes_t2/pcos/fatty_liver. Generator rejects otherwise.
2. **Allergen lookup table:** `almond/almendra → tree_nuts`, `whey/suero → dairy`, `oat/avena → gluten (unless certified)`, `soy/soya → soy`, `kefir → dairy`, `coconut milk → none (but check sulphites)`.
3. **GL audit:** every liquid recipe carries `_audit.gl_estimated`. If `GL > 10`, auto-strip diabetes/PCOS/fatty_liver from `recommendedForConditions`.
4. **Cultural tag:** culturally-specific items (mate, chicha morada, tepache, agua de jamaica) tagged `_audit.cultural_origin` for future micro-region split.

### Algorithm-side coupling (coordination with H1.5 variety + future Pareto)

- **Liquid cap per day:** `weight_loss` users → max 1 liquid meal/day; other goals → max 2/day. Enforced in Layer4 coherence. Reason: satiety drops with liquid-heavy diet → adherence churn.
- **Variety signal:** Jaccard penalty already covers tag overlap — liquid recipes share `liquid_meal` tag, so daily repetition penalized naturally.

### Initial 30 batch composition

| Category | Count | Slot | Format |
|----------|-------|------|--------|
| Jugos LatAm clásicos | 10 | snack | liquid |
| Smoothies funcionales | 10 | snack/breakfast | liquid |
| Mezclas/preparaciones virales | 10 | breakfast/snack | semi_solid |

3 exemplar JSONs documented in agent report (piña+linaza+chía, smoothie proteico cacao+plátano, chía pudding overnight). Owner approves → clinical-generator runs batch.

---

## 7. ADRs to write

| ADR | Title | Scope |
|---|---|---|
| ADR-0012 | Sex binary MVP + sex_at_birth rename | Document inclusion limitation + clinical rationale |
| ADR-0013 | dietary_pattern + cuisine_region + meal_format catalog fields | 3 additive fields + migration plan |
| ADR-0014 | Allergen freetext refuse-policy | P0 safety: never silently ignore |
| ADR-0015 | Liquid meal cap per day | Layer4 coherence constraint + adherence rationale |

---

## 8. Project structure after these changes

```
app/
├── core/
│   ├── config.py                          # +allergen_freetext_refuse policy flag
│   ├── errors.py
│   ├── ...
├── identity/                              # auth, signup
├── profile/
│   ├── domain/
│   │   ├── entities.py                    # UserProfile + dietary_pattern + conditions_freetext + allergens_freetext
│   │   └── region_mapper.py
│   ├── application/
│   │   └── use_cases.py                   # CompleteOnboarding + MVP segment gate
│   └── presentation/
│       ├── router.py
│       └── schemas.py                     # OnboardingRequest (extended)
├── nutrition/                             # BMR/TDEE/macros (legacy float, ADR-0009 Track C migration)
├── recipes/                               # catalog model + ingest
├── plan/
│   ├── domain/
│   │   ├── ports.py                       # 7 Protocols (Stage, RankingSignal, ConditionGate, Constraint, Solver, WeightVectorRepo, TasteProfileReader, RecentRecipesReader)
│   │   ├── context.py                     # PlanGenContext, MacroTargets, RecipeView, etc
│   │   ├── macro_calculator.py            # Decimal-strict H1.1-H1.3
│   │   ├── bmr_safety.py                  # Decimal-strict + safety floor H1.4
│   │   ├── recent_recipes.py              # RecentRecipesReader Protocol
│   │   ├── ranking_signals/
│   │   │   └── variety_jaccard.py         # H1.5 shipped
│   │   ├── condition_gates/               # H2: per-condition Strategy classes
│   │   ├── constraints.py                 # MacroEnvelope, DailyKcalEnvelope, LiquidCap
│   │   ├── inputs_hash.py                 # ADR-0010 helper
│   │   └── algorithm_version.py           # ADR-0011 version constant
│   ├── application/
│   │   ├── pipeline.py                    # Pipeline.run with budget
│   │   ├── create_plan.py                 # legacy orchestrator (Track C wiring pending)
│   │   ├── layer1_eligibility.py          # SQL filter + tree-nut defensive scan
│   │   ├── layer2_shortlist.py
│   │   ├── layer3_ranking.py
│   │   ├── layer4_coherence.py            # +LiquidCap constraint
│   │   ├── recalibration_saga.py          # H3
│   │   └── taste_profile.py
│   ├── infrastructure/                    # SQLAlchemy models, repos
│   └── presentation/
├── tracking/                              # food_log, weight_log, water_log
├── coach/
├── vision/
├── voice/
├── grocery/
├── gamification/
├── billing/
├── notifications/
└── shared/
    └── domain/
        ├── macro_tolerance.py             # Decimal constants single source
        ├── vocabularies.py                # closed enums single source (allergens/conditions/goals/activity/meal_times/locales/regions)
        └── value_objects.py

data/
├── meals/
│   ├── nova_meals_catalog.cleaned.json    # 2000 recipes (87 diabetes_t2 derecommended)
│   ├── nova_meals_catalog.cleaned.json.bak
│   └── liquid_batch_2026_06_01.json       # 30 jugos + smoothies + viral (post-owner-approval)

migrations/versions/
├── 0001_init.py
├── ...
├── 0007_idempotency_keys.py
├── 0008_recipe_micronutrients.py          # gi, gl, K, P, Fe, Ca, omega3, folate, pregnancy_safe
├── 0009_plan_algorithm_infra.py           # plan_versions, outbox, plan_weight_vectors
├── 0010_catalog_dietary_pattern.py        # dietary_pattern, cuisine_region, meal_format (TBD)
├── 0011_profile_onboarding_extensions.py  # dietary_pattern, freetext columns (TBD)
└── 0012_plan_recalibration_sagas.py       # H3 (TBD)

tests/
├── catalog/
│   └── test_enum_closure.py               # 7 tests, drift guard
├── clinical/
│   └── test_allergen_hard_exclude.py      # 4 tests, Layer1 invariants
├── plan/
│   └── property/
│       ├── strategies.py
│       ├── test_macro_invariants.py       # 8 properties × 200 examples
│       ├── test_bmr_safety_invariants.py  # 7 properties × 200 examples
│       ├── test_bmr_cross_check.py        # F1 risk: 1000 cases legacy vs new ≤1 kcal
│       └── test_variety_jaccard.py        # 7 properties for H1.5
├── unit/
│   ├── profile/
│   │   └── test_mvp_segment_gate.py       # 8 tests
│   └── ...

docs/
├── adr/
│   ├── 0001-allergen-condition-vocabulary.md
│   ├── ...
│   ├── 0009-decimal-strict-plan-algorithm-migration.md
│   ├── 0010-plan-inputs-hash-canonical-form.md
│   ├── 0011-algorithm-version-semver-policy.md
│   ├── 0012-sex-binary-mvp.md             # TBD
│   ├── 0013-catalog-dietary-pattern-fields.md  # TBD
│   ├── 0014-allergen-freetext-refuse-policy.md # TBD
│   └── 0015-liquid-meal-cap-per-day.md    # TBD
├── algorithms/
│   ├── MASTER_PLAN_ALGORITHM.md
│   ├── H1_FOUNDATION_REPORT.md
│   ├── ONBOARDING_FORM_AUDIT.md           # this file
│   ├── PRE_PROD_AUDIT.md
│   ├── CATALOG_AUDIT.md
│   ├── OPTION_A_SHIP_REPORT.md
│   └── SESSION_HANDOFF_2026-06-01.md
├── security/
├── ops/
└── team/

scripts/
├── audit_catalog.py
├── compute_embeddings.py
├── remap_catalog_enums.py
├── catalog_patches_2026_06_01.py
├── catalog_liquid_batch_2026_06_01.py     # TBD post-approval
└── ...
```

---

## 9. Risk register update — onboarding-induced risks

| # | Risk | Mitigation | Status |
|---|---|---|---|
| O1 | Free-text allergen silent exposure | Refuse + support route | P0 — schema ready |
| O2 | Vegan gets meat | Mandatory `dietary_pattern` field | P0 — schema ready |
| O3 | Height meter/cm confusion | Pydantic range + UI label | P1 |
| O4 | Athlete underestimated BMR | Optional bodyfat in step 2 + warning | P1 |
| O5 | "Otros…" routed to clinical gates | Freetext column, no filter | P1 |
| O6 | "Colesterol alto" → wrong condition | Map to `dyslipidemia` not `hypercholesterolemia` | P1 |
| O7 | Celiac written as allergen only | Write BOTH `celiac` + `gluten` | P1 |
| O8 | Liquid over-consumption → satiety drop → churn | Layer4 LiquidCap constraint | P1 — ADR-0015 |
| O9 | Smoothie hidden sugar diabetes harm | Catalog validator + GL audit on liquids | P1 — validators ready |
| O10 | Cultural mismatch (mate vs agua fresca) | `cuisine_region[]` + `_audit.cultural_origin` | P2 |
| O11 | Pediatric age sneaks past UI | Pydantic `age ≥ 18` reject | P1 |
| O12 | Geriatric (>80) Mifflin questionable | Reject + clinical review queue | P1 |
| O13 | Sex/gender misalignment for trans users | ADR-0012 internal rename `sex_at_birth` + helper text | P1 |
| O14 | `meals_per_day` defaulted wrong | Step 2 + warning fallback | P2 |
| O15 | Region inferred wrong (VPN/travel) | Profile override option | P2 |

---

## 10. Owner action checklist

### Must approve before next code work

- [ ] Approve `dietary_pattern` as new mandatory onboarding field (UI work for iOS)
- [ ] Approve `allergens_freetext` refuse-policy (UX implication: support route)
- [ ] Approve catalog field additions (`dietary_pattern`, `cuisine_region`, `meal_format`) → migration 0010
- [ ] Approve liquid batch of 30 generation by clinical-generator
- [ ] Approve label change "Talla (M)" → "Estatura (m, ej. 1.75)" for iOS team
- [ ] Approve condition mapping rules (Colesterol→dyslipidemia, Celiaquía→celiac+gluten)

### Can proceed without approval (low risk)

- ADR 0012-0015 drafts
- Pydantic schema extension drafts
- Migration 0010 draft (additive only)

---

## 11. What this DOES NOT cover

- iOS UI implementation (mobile team scope)
- A/B onboarding flow (single vs split screen) — design call
- Localization beyond es (en/pt/fr/de translation strings)
- Pediatric (<18) algorithm — separate clinical track
- Pregnancy/lactation flow — H2 segment unlock
- Coach LLM integration with `conditions_freetext` — coach module scope
