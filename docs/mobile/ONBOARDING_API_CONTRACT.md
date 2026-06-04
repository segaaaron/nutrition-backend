# NOVA Onboarding API Contract — Mobile (iOS + Android)

**Version:** 1.0 — 2026-06-01
**Audience:** iOS Swift / SwiftUI team + Android Kotlin / Jetpack Compose team
**Endpoint:** `POST /v1/profile/me/onboarding`
**Auth:** Bearer JWT (obtained via signup/login flow)
**Backend schema:** `app/profile/presentation/schemas.py::OnboardingRequest`
**Test contract:** `tests/unit/profile/test_onboarding_schema.py` (33 tests — mirror them in mobile unit tests)

---

## TL;DR

1. Mobile form submits **single JSON payload** to `POST /v1/profile/me/onboarding`.
2. **All Spanish UI labels map to English snake_case field names** (table below).
3. **Mandatory:** age, sex, weight, height (m OR cm), goal, activity, dietary_pattern.
4. **Conditional required:** `trimester` if pregnancy, `is_exclusively_breastfeeding` if lactation.
5. **Hard refuse:** `other_allergy` non-empty → server returns **422** with problem code; mobile shows support-redirect UI.
6. **MVP segment gate:** pregnancy / diabetes_t1 / diabetes_t2 / ckd return **422 `segment_unsupported_mvp:...`**; lactation accepted.

---

## 1. Endpoint

| Method | Path | Auth | Content-Type | Returns |
|--------|------|------|--------------|---------|
| POST | `/v1/profile/me/onboarding` | `Authorization: Bearer <jwt>` | `application/json` | 201 `ProfileResponse` |

Optional headers:
| Header | Purpose |
|--------|---------|
| `Accept-Language: es-PE` | Locale fallback inference (server picks region) |
| `X-Region: latam` | Override region detection |
| `Idempotency-Key: <uuid v4>` | Safe retries on flaky network (24h dedupe) |

---

## 2. Field map — UI label → API field

### Identity
| UI label | API field | Type | Required | Notes |
|----------|-----------|------|---------:|-------|
| Nombre completo / Full name | `name` | string (≤120) | No | Display only |

### Biometrics
| UI label | API field | Type | Required | Notes |
|----------|-----------|------|---------:|-------|
| Edad / Age | `age` | int 18-80 | **Yes** | Reject <18 (pediatric) / >80 (geriatric) client-side too |
| Sexo / Sex | `sex` | `"male" \| "female"` | **Yes** | Helper text: "Para calcular tu metabolismo basal" |
| Unidades / Units | `units` | `"metric" \| "imperial"` | No | Display preference only; payload always SI |
| Peso (kg) / Weight (kg) | `weight_kg` | Decimal 30-250 | **Yes** | Always kg in payload (convert lbs locally) |
| Estatura (m) / Height (m) | `height_m` | Decimal 1.20-2.40 | **Yes** OR `height_cm` | iOS form sends meters |
| Estatura (cm) / Height (cm) | `height_cm` | Decimal 120-240 | OR `height_m` | Android may prefer cm |
| % grasa corporal (opcional) | `bodyfat_pct` | Decimal 3-60 | No | Show ONLY if `activity_level == "extra_active"` |

### Goals
| UI label | API field | Type | Required | Notes |
|----------|-----------|------|---------:|-------|
| Objetivo / Goal | `goal` | enum (5 values) | **Yes** | See enum table |
| Nivel de actividad | `activity_level` | enum (5 values) | **Yes** | See enum table |
| Dieta | `dietary_pattern` | enum (4 values) | **Yes** | NEW field — add chip row |

### Conditions (multi-select chips)
| UI label | API value | Type | Required | Notes |
|----------|-----------|------|---------:|-------|
| Diabetes tipo 2 | `"diabetes_t2"` | array item | No | **GATED 422** today |
| Hipertensión | `"hypertension"` | array item | No | OK |
| Celiaquía | `"celiac"` + `"gluten"` in allergies | both fields | No | Mobile sends BOTH |
| Colesterol alto | `"dyslipidemia"` | array item | No | **NOT** `hypercholesterolemia` |
| Hipotiroidismo | `"hypothyroidism"` | array item | No | OK |
| Lactancia / Breastfeeding | `"lactation"` | array item | No | Requires `is_exclusively_breastfeeding` |
| Embarazo / Pregnancy | `"pregnancy"` | array item | No | **GATED 422** today, requires `trimester` |
| Otros… / Others… | `other_condition` | free text string | No | Stored as PII; NOT routed to nutrition filter; UI shows warning |
| Ninguna / None | (empty array `[]`) | array | — | Send empty list, not literal "none" |

### Allergens (multi-select chips)
| UI label | API value | Required | Notes |
|----------|-----------|---------:|-------|
| Lácteos | `"dairy"` | No | |
| Gluten | `"gluten"` | No | |
| Frutos secos | `"tree_nuts"` | No | |
| Mariscos | `"shellfish"` | No | |
| Huevo | `"egg"` | No | |
| Soya | `"soy"` | No | |
| Otra alergia… | `other_allergy` | **REFUSE non-empty** | See §4 — server returns 422 |
| Ninguna | (empty array `[]`) | — | |

### Conditional fields (show only when relevant)
| UI label | API field | Type | Required when | Notes |
|----------|-----------|------|----------------|-------|
| ¿En qué trimestre estás? | `trimester` | `"first" \| "second" \| "third"` | `medical_conditions` contains `pregnancy` | Show only if pregnancy chip selected |
| ¿Estás amamantando exclusivamente? | `is_exclusively_breastfeeding` | bool | `medical_conditions` contains `lactation` | true → +500 kcal/day; false → +250 kcal partial |

### Region / locale (optional)
| UI label | API field | Type | Required | Notes |
|----------|-----------|------|---------:|-------|
| País | `country` | ISO-3166-1 alpha-2 string | No | Server uses for region inference |
| Idioma | `locale` | `"en" \| "es" \| "pt" \| "fr" \| "de"` | No | Falls back to `Accept-Language` header |
| Tema | `theme` | `"light" \| "dark"` | No | Default `"light"` |

---

## 3. Enum reference (closed sets — strict server validation)

```typescript
// TypeScript / Swift / Kotlin equivalents

type Sex = "male" | "female";

type Units = "metric" | "imperial";

type Goal =
  | "weight_loss"     // "Bajar de peso"
  | "maintain"        // "Mantener peso"
  | "muscle_gain"     // "Ganar músculo"
  | "weight_gain"     // "Ganar peso"
  | "health";         // "Mejorar mi salud general"

type ActivityLevel =
  | "sedentary"            // "Sedentario · 0-1 día/sem"
  | "lightly_active"       // "Ligero · 1-2 días/sem"
  | "moderately_active"    // "Moderado · 3-4 días/sem"
  | "very_active"          // "Activo · 5-6 días/sem"
  | "extra_active";        // "Atleta · 7 días/sem"

type DietaryPattern =
  | "omnivore"      // "🍖 Omnívoro"
  | "pescatarian"   // "🐟 Pescetariano"
  | "vegetarian"    // "🥗 Vegetariano"
  | "vegan";        // "🌱 Vegano"

type MobileCondition =
  | "diabetes_t2" | "hypertension" | "celiac" | "dyslipidemia"
  | "hypothyroidism" | "lactation" | "pregnancy";

type MobileAllergen =
  | "dairy" | "gluten" | "tree_nuts" | "shellfish" | "egg" | "soy";

type Trimester = "first" | "second" | "third";

type Theme = "light" | "dark";

type Locale = "en" | "es" | "pt" | "fr" | "de";
```

---

## 4. Request payload examples

### 4.1 Happy path — omnivore weight loss

```json
{
  "name": "Miguel Saravia",
  "age": 30,
  "sex": "male",
  "units": "metric",
  "weight_kg": "72.0",
  "height_m": "1.75",
  "goal": "weight_loss",
  "activity_level": "moderately_active",
  "dietary_pattern": "omnivore",
  "medical_conditions": [],
  "other_condition": null,
  "allergies": [],
  "other_allergy": null,
  "trimester": null,
  "is_exclusively_breastfeeding": null,
  "country": "PE",
  "locale": "es",
  "theme": "light"
}
```

**Response 201:**
```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "Miguel Saravia",
  "age": 30,
  "sex": "male",
  "units": "metric",
  "weight_kg": "72.0",
  "height_cm": "175.0",
  "goal": "weight_loss",
  "activity_level": "moderately_active",
  "medical_conditions": [],
  "other_condition": null,
  "allergies": [],
  "other_allergy": null,
  "country": "PE",
  "region": "latam",
  "locale": "es",
  "theme": "light",
  "onboarding_completed": true,
  "updated_at": "2026-06-01T15:00:00Z"
}
```

### 4.2 Athlete with bodyfat (Cunningham BMR)

```json
{
  "age": 28,
  "sex": "male",
  "weight_kg": "82.0",
  "height_m": "1.82",
  "bodyfat_pct": "12.5",
  "goal": "muscle_gain",
  "activity_level": "extra_active",
  "dietary_pattern": "omnivore",
  "medical_conditions": [],
  "allergies": []
}
```

### 4.3 Celiac with gluten allergy (BOTH fields)

```json
{
  "age": 35,
  "sex": "female",
  "weight_kg": "60.0",
  "height_m": "1.65",
  "goal": "health",
  "activity_level": "lightly_active",
  "dietary_pattern": "vegetarian",
  "medical_conditions": ["celiac"],
  "allergies": ["gluten"]
}
```

**iOS / Android logic:** When user toggles "Celiaquía" chip, automatically add `"gluten"` to allergies array AND `"celiac"` to conditions array. Toggle off → remove both.

### 4.4 Lactation (H2.1 lifted)

```json
{
  "age": 32,
  "sex": "female",
  "weight_kg": "65.0",
  "height_m": "1.68",
  "goal": "health",
  "activity_level": "lightly_active",
  "dietary_pattern": "omnivore",
  "medical_conditions": ["lactation"],
  "is_exclusively_breastfeeding": true,
  "allergies": []
}
```

**iOS / Android UI:** When user selects "Lactancia" chip, show modal:
> ¿Estás amamantando exclusivamente?
> [ Sí ] [ No, parcial / suplemento ]

Map: Yes → `is_exclusively_breastfeeding: true`; No → `is_exclusively_breastfeeding: false`. **Without this field, server returns 422.**

### 4.5 Pregnancy (H2.2 — STILL GATED, mobile must handle 422)

```json
{
  "age": 30,
  "sex": "female",
  "weight_kg": "68.0",
  "height_m": "1.68",
  "goal": "health",
  "activity_level": "lightly_active",
  "dietary_pattern": "omnivore",
  "medical_conditions": ["pregnancy"],
  "trimester": "second",
  "allergies": []
}
```

**Server response 422** (today):
```json
{
  "type": "urn:nova:problem:plan:segment-unsupported-mvp",
  "title": "Segment unsupported in MVP",
  "status": 422,
  "detail": "segment_unsupported_mvp:conditions:pregnancy"
}
```

**iOS / Android UX:**
> Tu segmento (embarazo) aún no está disponible en NOVA.
> Te avisamos cuando se active.
> [ Continuar sin esta condición ] [ Salir ]

---

## 5. Error contract (RFC 7807 Problem Details)

All errors come as `application/problem+json` with status code + URN `type`.

| Status | Type URN | Detail format | UI action |
|-------:|----------|---------------|-----------|
| 400 | `urn:nova:problem:validation:invalid-field` | Field name + reason | Show inline field error |
| 422 | `urn:nova:problem:plan:allergen-unmapped-requires-review` | `allergen_unmapped_requires_review` | Block submit + show support modal (§6.1) |
| 422 | `urn:nova:problem:plan:segment-unsupported-mvp` | `segment_unsupported_mvp:conditions:<list>` OR `:region:<region>` | Show "segmento no disponible" + CTA waitlist |
| 422 | `urn:nova:problem:plan:onboarding-incomplete` | `onboarding_incomplete` OR `profile_missing:<field>` | Re-prompt missing field |
| 422 | `urn:nova:problem:plan:trimester-required-for-pregnancy` | `trimester_required_for_pregnancy` | Force trimester picker |
| 422 | `urn:nova:problem:plan:breastfeeding-status-required-for-lactation` | `breastfeeding_status_required_for_lactation` | Force breastfeeding modal |
| 422 | `urn:nova:problem:plan:height-required` | `height_required` | Re-prompt height field |
| 422 | `urn:nova:problem:plan:pediatric-outside-mvp-scope` | `pediatric_outside_mvp_scope` | Age check — under 18 not supported |
| 422 | `urn:nova:problem:plan:geriatric-requires-specialist-review` | `geriatric_requires_specialist_review` | Age check — over 80 needs review |
| 401 | `urn:nova:problem:auth:unauthenticated` | — | Re-login |
| 403 | `urn:nova:problem:auth:forbidden` | — | Permission missing |
| 426 | `urn:nova:problem:client:upgrade-required` | `X-Min-Client-Version` header included | Force app update |
| 429 | `urn:nova:problem:rate-limit:exceeded` | `Retry-After: <s>` header | Backoff + retry |
| 500 | `urn:nova:problem:server:internal-error` | — | Generic error + retry button |
| 503 | `urn:nova:problem:server:unavailable` | `Retry-After: <s>` | Wait + retry |

### 5.1 Sample 422 response — allergen freetext refuse

```http
HTTP/1.1 422 Unprocessable Entity
Content-Type: application/problem+json

{
  "type": "urn:nova:problem:plan:allergen-unmapped-requires-review",
  "title": "Custom allergen requires manual review",
  "status": 422,
  "detail": "allergen_unmapped_requires_review",
  "instance": "/v1/profile/me/onboarding",
  "support_url": "https://nova-nutrition.com/support/allergen-review"
}
```

### 5.2 Sample 422 response — pregnancy gate

```http
HTTP/1.1 422 Unprocessable Entity
Content-Type: application/problem+json

{
  "type": "urn:nova:problem:plan:segment-unsupported-mvp",
  "title": "Segment unsupported in MVP",
  "status": 422,
  "detail": "segment_unsupported_mvp:conditions:pregnancy",
  "instance": "/v1/profile/me/onboarding"
}
```

---

## 6. Required mobile UX patterns

### 6.1 Allergen freetext refuse modal

If user enters non-empty text in "Otra alergia…" → on submit, server returns 422 + `allergen_unmapped_requires_review`. iOS / Android show modal:

```
┌────────────────────────────────────────┐
│  ⚠️  Alergia personalizada              │
│                                        │
│  Tu alergia "ajonjolí" requiere        │
│  revisión manual antes de generar      │
│  tu plan.                              │
│                                        │
│  No podemos filtrar automáticamente    │
│  alergias fuera de nuestra lista.      │
│                                        │
│  [  Contactar soporte  ]               │
│  [  Quitar alergia personalizada  ]    │
└────────────────────────────────────────┘
```

### 6.2 Disclaimer placement

**Signup screen (before form fields):**
```
NOVA es un planificador nutricional. No reemplaza
consulta médica. Si tienes una condición médica,
consulta a tu doctor antes de seguir tu plan.

[ ✓ Entiendo y acepto ]
```

**Per-plan footer (visible always in plan view):**
```
ℹ️ Plan informativo, no consejo médico.
   Consulta a tu médico ante dudas.
```

### 6.3 Conditional field reveal

iOS / Android conditional logic:

```pseudo
if "extra_active" in activity_level:
    show optional question "¿Conoces tu % de grasa?"

if "pregnancy" in medical_conditions:
    require trimester picker (3 buttons: 1er / 2do / 3er trimestre)

if "lactation" in medical_conditions:
    require modal "¿Estás amamantando exclusivamente?"

if "celiac" toggled ON:
    auto-add "gluten" to allergens (and disable that chip)
if "celiac" toggled OFF:
    remove auto-added "gluten"

if "Otros…" condition tapped:
    show text input + warning "Tu condición personalizada no se
    filtra automáticamente. Revisa cada receta con tu médico."
```

### 6.4 Label clarifications

- `Talla (M)` → **change to `Estatura (m, ej. 1.75)`** (M was ambiguous).
- `Sexo` → add helper text: "Para calcular tu metabolismo basal".
- `Atleta · 7 días/sem` → on selection, hint: "Te preguntaremos % grasa después para mayor precisión".

### 6.5 Network error handling

Use `Idempotency-Key: <uuid v4>` on every onboarding submit. If first request times out and second succeeds with same key, server returns same response (no duplicate profile). 24h dedupe window.

```swift
// iOS Swift
let key = UUID().uuidString
request.setValue(key, forHTTPHeaderField: "Idempotency-Key")
```

```kotlin
// Android Kotlin
val key = UUID.randomUUID().toString()
request.addHeader("Idempotency-Key", key)
```

---

## 7. Validation rules (mobile = server parity)

Mirror these in client-side validators to prevent unnecessary network round trips:

| Field | Min | Max | Pattern / Enum |
|-------|----:|----:|----------------|
| `name` | — | 120 chars | Any text |
| `age` | 18 | 80 | Integer |
| `weight_kg` | 30.0 | 250.0 | Decimal (1 dp ok) |
| `height_m` | 1.20 | 2.40 | Decimal (2 dp) |
| `height_cm` | 120.0 | 240.0 | Decimal (1 dp ok) |
| `bodyfat_pct` | 3.0 | 60.0 | Decimal (1 dp) |
| `sex` | — | — | enum (male/female) |
| `goal` | — | — | enum (5 values) |
| `activity_level` | — | — | enum (5 values) |
| `dietary_pattern` | — | — | enum (4 values) |
| `medical_conditions` | 0 items | 6 items | enum array |
| `allergies` | 0 items | 7 items | enum array |
| `other_condition` | — | 200 chars | Free text (PII column) |
| `other_allergy` | — | 200 chars | **Non-empty refuses** |
| `trimester` | — | — | enum (first/second/third) |
| `is_exclusively_breastfeeding` | — | — | boolean |
| `country` | 2 chars | 2 chars | ISO-3166-1 alpha-2 |
| `locale` | — | — | enum (en/es/pt/fr/de) |

---

## 8. Cross-platform code skeletons

### 8.1 Swift (iOS) data model

```swift
struct OnboardingRequest: Encodable {
    let name: String?
    let age: Int
    let sex: Sex
    let units: Units
    let weight_kg: Decimal
    let height_m: Decimal?
    let height_cm: Decimal?
    let bodyfat_pct: Decimal?
    let goal: Goal
    let activity_level: ActivityLevel
    let dietary_pattern: DietaryPattern
    let medical_conditions: [MobileCondition]
    let other_condition: String?
    let allergies: [MobileAllergen]
    let other_allergy: String?
    let trimester: Trimester?
    let is_exclusively_breastfeeding: Bool?
    let country: String?
    let locale: Locale?
    let theme: Theme
}

enum Sex: String, Encodable { case male, female }
enum Goal: String, Encodable {
    case weight_loss, maintain, muscle_gain, weight_gain, health
}
enum DietaryPattern: String, Encodable {
    case omnivore, pescatarian, vegetarian, vegan
}
enum Trimester: String, Encodable { case first, second, third }
// ... etc.
```

### 8.2 Kotlin (Android) data class

```kotlin
@Serializable
data class OnboardingRequest(
    val name: String? = null,
    val age: Int,
    val sex: Sex,
    val units: Units = Units.METRIC,
    val weight_kg: BigDecimal,
    val height_m: BigDecimal? = null,
    val height_cm: BigDecimal? = null,
    val bodyfat_pct: BigDecimal? = null,
    val goal: Goal,
    val activity_level: ActivityLevel,
    val dietary_pattern: DietaryPattern,
    val medical_conditions: List<MobileCondition> = emptyList(),
    val other_condition: String? = null,
    val allergies: List<MobileAllergen> = emptyList(),
    val other_allergy: String? = null,
    val trimester: Trimester? = null,
    val is_exclusively_breastfeeding: Boolean? = null,
    val country: String? = null,
    val locale: Locale? = null,
    val theme: Theme = Theme.LIGHT,
)

@Serializable enum class Sex { @SerialName("male") MALE, @SerialName("female") FEMALE }
@Serializable enum class Goal {
    @SerialName("weight_loss") WEIGHT_LOSS,
    @SerialName("maintain") MAINTAIN,
    @SerialName("muscle_gain") MUSCLE_GAIN,
    @SerialName("weight_gain") WEIGHT_GAIN,
    @SerialName("health") HEALTH,
}
@Serializable enum class DietaryPattern {
    @SerialName("omnivore") OMNIVORE,
    @SerialName("pescatarian") PESCATARIAN,
    @SerialName("vegetarian") VEGETARIAN,
    @SerialName("vegan") VEGAN,
}
// ... etc.
```

### 8.3 Common JSON serialization rules

- All keys: `snake_case`
- Decimals: serialize as JSON string (`"72.0"`) — NOT float. Avoids precision loss on round-trip.
- Booleans: `true` / `false` (lowercase).
- Null values: explicit `null` for optional unset fields OR omit entirely; both accepted.
- Arrays: `[]` for empty (NOT `null`).
- Dates: ISO-8601 UTC with `Z` suffix.

---

## 9. Versioning + breaking changes

| Rule | Applied |
|------|---------|
| Additive minors only | New optional fields can be added without version bump |
| Mobile clients on older schema | Server tolerates extra fields stripped by old clients |
| Major version bump | New path `/v2/...`; `/v1` frozen with 90-day sunset header |
| Algorithm version exposed | Plan responses include `algorithm_version` semver string |

Mobile clients SHOULD log `algorithm_version` from plan responses for crash report context.

---

## 10. Testing reference

Mobile QA can replicate backend test scenarios. Each scenario below is implemented in `tests/unit/profile/test_onboarding_schema.py`:

| Scenario | Test name |
|----------|-----------|
| Minimum omnivore | `test_minimum_required_omnivore` |
| Height cm alt to height m | `test_height_cm_alternative_to_height_m` |
| Athlete with bodyfat | `test_athlete_with_bodyfat` |
| All dietary patterns | `test_all_dietary_patterns_accepted` (4 cases) |
| Celiac dual write | `test_celiac_writes_both_condition_and_gluten_allergen` |
| Colesterol → dyslipidemia | `test_colesterol_alto_maps_to_dyslipidemia` |
| Lactation exclusive | `test_lactation_with_breastfeeding_status_exclusive` |
| Lactation partial | `test_lactation_partial_breastfeeding` |
| Pregnancy with trimester | `test_pregnancy_with_trimester` |
| Allergen freetext refuse | `test_allergen_freetext_refuses` |
| Height both missing | `test_height_missing_both_refuses` |
| Pregnancy missing trimester | `test_pregnancy_without_trimester_refuses` |
| Lactation missing flag | `test_lactation_without_breastfeeding_flag_refuses` |
| Age out of bounds | `test_age_outside_18_80_refuses` (4 cases) |
| Weight out of bounds | `test_weight_outside_30_250_refuses` (2 cases) |
| Height out of bounds | `test_height_m_outside_1_20_2_40_refuses` (2 cases) |
| Missing dietary | `test_missing_dietary_pattern_refuses` |
| Unknown dietary | `test_unknown_dietary_pattern_refuses` |
| Unknown condition | `test_unknown_condition_refuses` |
| Unknown allergen | `test_unknown_allergen_refuses` |
| Extra field rejected | `test_extra_field_refuses` |
| Other condition freetext OK | `test_other_condition_freetext_persists_does_not_refuse` |
| Height conversion | `test_height_m_to_cm_conversion_precision` |
| Height_cm wins precedence | `test_height_cm_wins_when_both_present` |

**33 backend tests total** — mobile teams should mirror these in iOS XCTest / Android JUnit.

---

## 11. After onboarding succeeds — next call

```http
POST /v1/plan/generate
Authorization: Bearer <jwt>
Idempotency-Key: <uuid>
Prefer: respond-async
```

Returns `201 Plan` (if generation completed <800ms) OR `202 + job_id + status_url` (async). See `docs/algorithms/MASTER_PLAN_ALGORITHM.md` §7 API endpoints + future `docs/mobile/PLAN_API_CONTRACT.md` (forthcoming).

---

## 12. Mobile owner action items

| Priority | Item | Estimación |
|----------|------|------------|
| P0 | Add `dietary_pattern` chip row UI between Objetivo and Actividad | 4h |
| P0 | Implement `other_allergy` refuse modal (§6.1) | 4h |
| P0 | Add signup disclaimer + per-plan footer (§6.2) | 4h |
| P0 | Change "Talla (M)" label → "Estatura (m, ej. 1.75)" | 30min |
| P1 | Add "Sexo" helper text | 30min |
| P1 | Add bodyfat_pct optional step 2 (when `extra_active`) | 4h |
| P1 | Add "Otros…" condition warning UI | 2h |
| P1 | Auto-link Celiaquía → gluten allergen | 2h |
| P1 | Add trimester picker conditional on pregnancy chip | 4h |
| P1 | Add breastfeeding exclusivity modal conditional on lactation chip | 2h |
| P1 | Implement RFC 7807 error parser + each problem-type → UI flow | 1d |
| P1 | Implement Idempotency-Key on submit | 2h |
| P2 | Unit tests mirroring backend's 33 contract tests | 1d |
| P2 | Localization for en / pt / fr / de | 2d |

---

## 13. Status of fields backend-side

| Field | Pydantic shipped | Domain entity shipped | DB migration | Use case wired |
|-------|:----------------:|:---------------------:|:------------:|:--------------:|
| `name`, `age`, `sex`, `weight_kg`, `height_cm` | ✅ | ✅ | ✅ | ✅ |
| `height_m` | ✅ | n/a (converted) | n/a | ✅ |
| `bodyfat_pct` | ✅ | ✅ | ❌ pending migration 0010 | ⏸ |
| `dietary_pattern` | ✅ | ✅ | ❌ pending migration 0010 | ⏸ |
| `trimester` | ✅ | ✅ | ❌ pending migration 0010 | ⏸ |
| `is_exclusively_breastfeeding` | ✅ | ✅ | ❌ pending migration 0010 | ⏸ |
| `other_condition`, `other_allergy` | ✅ | ✅ | ✅ (existing PII cols) | ✅ |
| `medical_conditions`, `allergies` | ✅ | ✅ | ✅ | ✅ |
| `country`, `locale`, `theme` | ✅ | ✅ | ✅ | ✅ |

**Owner action backend-side (P1):** alembic migration 0010 adding new columns to `user_profiles` table. Until then, new fields stored at app-layer only (not persisted across restarts). Mobile team can integrate now — schema accepted, validators run, but new fields not yet persisted.

---

## 14. Contract version + change log

| Version | Date | Change |
|---------|------|--------|
| 1.0 | 2026-06-01 | Initial mobile contract published. Schema with dietary_pattern, bodyfat_pct, trimester, is_exclusively_breastfeeding, height_m, RFC 7807 error map, 33 backend tests. |

---

End of contract.
