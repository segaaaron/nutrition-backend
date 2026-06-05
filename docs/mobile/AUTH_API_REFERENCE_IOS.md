# Auth API Reference — iOS Mapping Guide

**Audience:** iOS engineer mapping NOVA auth endpoints to Swift `Codable` structs.
**Backend version:** 2026-06-05 (post i18n feature)
**Base URL:** `https://api.nova-nutrition.app` (prod) | `https://staging-api.nova-nutrition.app` (staging)
**No global API version prefix.** Routes are bare (`/auth/*`, `/me/*`).
**Content-Type:** `application/json` for all request bodies. UTF-8.
**Strict mode:** all request schemas have `extra = "forbid"` — extra fields → HTTP 422.

---

## Cross-cutting headers

| Header | Direction | Required | Notes |
|--------|-----------|----------|-------|
| `Authorization: Bearer <access_token>` | request | only on `/me/*` + protected endpoints | JWT short-lived (15min default) |
| `Accept-Language` | request | NO (recommended) | RFC 7231 q-values OK (`es-419,en;q=0.8`). Backend supports `es` + `en`. Unsupported → ES fallback. iOS `URLSession` sends auto from `NSLocale.preferredLanguages`. |
| `Content-Type: application/json` | request | YES on body endpoints | |
| `Retry-After` | response | conditional | on `429` + `503` (RFC 6585). Integer seconds. |
| `Content-Type: application/problem+json` | response | conditional | on 4xx/5xx errors (RFC 7807). |

---

## Error envelope (RFC 7807) — applies to ALL endpoints

Whenever a non-2xx is returned, the body is an `ApplicationProblem` document. iOS should decode this for any non-2xx response.

```json
{
  "type": "urn:nova:problem:unauthenticated",
  "title": "No autenticado",
  "status": 401,
  "detail": "Token faltante o inválido",
  "instance": "/auth/login",
  "i18n_key": "unauthenticated"
}
```

| Field | Type | Notes |
|-------|------|-------|
| `type` | string (URN) | Machine-readable identifier. **ALWAYS EN canonical.** Use this for switch/case in iOS. |
| `title` | string | Short human-readable. **Translated** per `Accept-Language` (es/en). |
| `status` | int | HTTP status code mirror. |
| `detail` | string \| null | Full human-readable. **Translated** per `Accept-Language`. |
| `instance` | string \| null | URL path of failing request. |
| `i18n_key` | string \| null | Canonical EN snake_case key. For client-side i18n if iOS prefers to translate locally. |

**Swift mapping:**
```swift
struct ApplicationProblem: Codable, Error {
    let type: String
    let title: String
    let status: Int
    let detail: String?
    let instance: String?
    let i18nKey: String?

    enum CodingKeys: String, CodingKey {
        case type, title, status, detail, instance
        case i18nKey = "i18n_key"
    }
}
```

---

## 1. `POST /auth/register`

Crea nueva cuenta. Returns token pair + user_id.

### Request

```json
{ "email": "miguel@example.com", "password": "correct horse battery staple" }
```

| Field | Type | Constraints |
|-------|------|-------------|
| `email` | string | RFC 5322 valid email |
| `password` | string | `min_length=8` |

### Response — 201 Created

```json
{
  "access_token": "eyJhbGc...",
  "refresh_token": "AbCdEfGh...",
  "token_type": "bearer",
  "user_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### Rate limit
Per-email rate limit (`rate_limit_auth_per_min` env, default 5/min). 429 + `Retry-After`.

### Swift mapping

```swift
struct RegisterRequest: Codable {
    let email: String
    let password: String
}

struct TokenPairResponse: Codable {
    let accessToken: String
    let refreshToken: String
    let tokenType: String  // always "bearer"
    let userId: UUID

    enum CodingKeys: String, CodingKey {
        case accessToken = "access_token"
        case refreshToken = "refresh_token"
        case tokenType = "token_type"
        case userId = "user_id"
    }
}
```

---

## 2. `POST /auth/login`

Login email + password.

### Request

```json
{ "email": "miguel@example.com", "password": "correct horse battery staple" }
```

| Field | Type | Constraints |
|-------|------|-------------|
| `email` | string | RFC 5322 valid email |
| `password` | string | no length constraint (only on register) |

### Response — 200 OK
`TokenPairResponse` (same as register).

### Errors comunes
- `401 urn:nova:problem:unauthenticated` — credenciales inválidas
- `429 urn:nova:problem:rate_limited` — exceeded per-email limit

### Swift mapping

```swift
struct LoginRequest: Codable {
    let email: String
    let password: String
}
```

---

## 3. `POST /auth/oauth/{provider}`

OAuth login con Google o Apple. Path param `{provider}` = `google` | `apple`.

### Request

```json
{ "id_token": "eyJhbGc..." }
```

| Field | Type | Constraints |
|-------|------|-------------|
| `id_token` | string | `min_length=20` |

Path: `/auth/oauth/google` or `/auth/oauth/apple`

### Response — 200 OK
`TokenPairResponse`.

### Swift mapping

```swift
enum OAuthProvider: String, Codable {
    case google
    case apple
}

struct OAuthLoginRequest: Codable {
    let idToken: String

    enum CodingKeys: String, CodingKey {
        case idToken = "id_token"
    }
}
```

iOS sends Apple's `identityToken` from `ASAuthorizationAppleIDCredential` or Google's ID token from `GIDSignIn`.

---

## 4. `POST /auth/refresh`

Renueva token pair. Rotación de refresh_token (old token invalidado).

### Request

```json
{ "refresh_token": "AbCdEfGh..." }
```

| Field | Type | Constraints |
|-------|------|-------------|
| `refresh_token` | string | `min_length=32` |

### Response — 200 OK
`TokenPairResponse` (nuevo par; old refresh_token invalidado server-side).

### Errors comunes
- `401 urn:nova:problem:unauthenticated` — refresh_token inválido/expirado/revocado

### Swift mapping

```swift
struct RefreshRequest: Codable {
    let refreshToken: String

    enum CodingKeys: String, CodingKey {
        case refreshToken = "refresh_token"
    }
}
```

---

## 5. `POST /auth/logout`

Logout. Invalida refresh_token + denylist access_token (Redis JTI).

### Request

```json
{ "refresh_token": "AbCdEfGh..." }
```

Headers:
- `Authorization: Bearer <access_token>` opcional (recomendado para denylist access)

| Field | Type | Constraints |
|-------|------|-------------|
| `refresh_token` | string | `min_length=32` |

### Response — 204 No Content
Sin body.

### Swift mapping

```swift
struct LogoutRequest: Codable {
    let refreshToken: String

    enum CodingKeys: String, CodingKey {
        case refreshToken = "refresh_token"
    }
}
```

---

## 6. `POST /auth/otp/send`

Envía OTP por email. 6 dígitos. Locale del email determinado por D5: `profile.locale` (si user existe) > `Accept-Language` > `"es"`.

### Request

```json
{ "email": "miguel@example.com", "purpose": "register" }
```

| Field | Type | Allowed |
|-------|------|---------|
| `email` | string | RFC 5322 |
| `purpose` | string | `"register"` \| `"reset"` \| `"login"` |

Headers:
- `Accept-Language: es-419,en;q=0.8` (recomendado para signup anon — sin profile aún)

### Response — 202 Accepted

```json
{ "status": "sent" }
```

**Dev env only:** incluye `"dev_code": "123456"` para QA testing sin email worker.

```json
{ "status": "sent", "dev_code": "123456" }
```

### Rate limit
Per-email (`rate_limit_auth_per_min`). 429 + `Retry-After`.

### Email locale
- Signup (`register`) anónimo: usa `Accept-Language` header → fallback ES
- Reset password: si profile existe → `profile.locale` gana
- Login: misma regla que reset

### Swift mapping

```swift
enum OtpPurpose: String, Codable {
    case register
    case reset
    case login
}

struct SendOtpRequest: Codable {
    let email: String
    let purpose: OtpPurpose
}

struct SendOtpResponse: Codable {
    let status: String           // "sent"
    let devCode: String?         // only in dev env

    enum CodingKeys: String, CodingKey {
        case status
        case devCode = "dev_code"
    }
}
```

---

## 7. `POST /auth/otp/verify`

Verifica OTP. Returns token pair si correcto.

### Request

```json
{ "email": "miguel@example.com", "purpose": "register", "code": "123456" }
```

| Field | Type | Constraints |
|-------|------|-------------|
| `email` | string | RFC 5322 |
| `purpose` | string | `"register"` \| `"reset"` \| `"login"` |
| `code` | string | exactamente 6 caracteres |

### Response — 200 OK
`TokenPairResponse`.

### Errors comunes
- `400 urn:nova:problem:business_rule` (`i18n_key: otp_invalid`) — code wrong
- `400` (`i18n_key: otp_expired`) — code expirado (TTL 10min default)
- `429 urn:nova:problem:rate_limited` — too many attempts

### Swift mapping

```swift
struct VerifyOtpRequest: Codable {
    let email: String
    let purpose: OtpPurpose
    let code: String
}
```

---

## 8. `DELETE /me`

GDPR account deletion. Soft-delete con grace period (30d default). Returns scheduled deletion timestamp.

Headers: `Authorization: Bearer <access_token>` REQUIRED.

### Request
Sin body.

### Response — 202 Accepted

```json
{
  "status": "scheduled",
  "scheduled_for": "2026-07-05T14:30:00Z"
}
```

| Field | Type | Notes |
|-------|------|-------|
| `status` | string | always `"scheduled"` |
| `scheduled_for` | string (ISO 8601 UTC) | Hard delete date. Grace period 30 días. |

### Swift mapping

```swift
struct DeletionScheduledResponse: Codable {
    let status: String           // "scheduled"
    let scheduledFor: Date

    enum CodingKeys: String, CodingKey {
        case status
        case scheduledFor = "scheduled_for"
    }
}
```

iOS `JSONDecoder` config:
```swift
let decoder = JSONDecoder()
decoder.dateDecodingStrategy = .iso8601
```

---

## 9. `POST /me/cancel-deletion`

Cancela deletion scheduled (durante grace period).

Headers: `Authorization: Bearer <access_token>` REQUIRED.

### Request
Sin body.

### Response — 200 OK

```json
{ "cancelled": true }
```

### Swift mapping

```swift
struct CancellationResponse: Codable {
    let cancelled: Bool
}
```

---

## 10. `GET /me/export`

GDPR Article 15 — data export. Returns JSON blob con toda data usuario.

Headers: `Authorization: Bearer <access_token>` REQUIRED.

### Request
Sin body.

### Response — 200 OK

```json
{
  "user": { "id": "...", "email": "...", "created_at": "...", "...": "..." },
  "note": "..."
}
```

| Field | Type | Notes |
|-------|------|-------|
| `user` | object | Full user blob (variable schema). |
| `note` | string | Disclaimer/info text. |

### Swift mapping

Dado que `user` es heterogéneo, iOS puede usar `[String: AnyCodable]` o decodear como `Data` raw:

```swift
struct ExportResponse: Codable {
    let user: [String: AnyCodable]  // requiere AnyCodable lib (ej. flight-school/anycodable)
    let note: String
}
```

Alternativa simple: decodear `user` como `Data` y entregar al usuario sin parsear.

---

## Locale propagation (i18n feature 2026-06-05)

**iOS no necesita hacer nada especial.** `URLSession` envía `Accept-Language` auto basado en `NSLocale.preferredLanguages`.

**Verificación recomendada iOS:**
```swift
let session = URLSession(configuration: .default)
// URLSession agrega Accept-Language auto. Verificar con Charles/Proxyman.
```

**Forzar locale específico (override device):**
```swift
var request = URLRequest(url: url)
request.setValue("es-419,es;q=0.9", forHTTPHeaderField: "Accept-Language")
```

**Impacto en endpoints auth:**
- `POST /auth/otp/send`: email idioma device automático
- Errors (cualquier endpoint): `title` + `detail` idioma device automático
- `POST /auth/register` + `POST /auth/login`: tokens neutrales, sin texto traducible

---

## Resumen tabla endpoints auth

| Endpoint | Method | Auth | Status | Request | Response |
|----------|--------|------|--------|---------|----------|
| `/auth/register` | POST | NO | 201 | `RegisterRequest` | `TokenPairResponse` |
| `/auth/login` | POST | NO | 200 | `LoginRequest` | `TokenPairResponse` |
| `/auth/oauth/{provider}` | POST | NO | 200 | `OAuthLoginRequest` | `TokenPairResponse` |
| `/auth/refresh` | POST | NO | 200 | `RefreshRequest` | `TokenPairResponse` |
| `/auth/logout` | POST | optional Bearer | 204 | `LogoutRequest` | (none) |
| `/auth/otp/send` | POST | NO | 202 | `SendOtpRequest` | `SendOtpResponse` |
| `/auth/otp/verify` | POST | NO | 200 | `VerifyOtpRequest` | `TokenPairResponse` |
| `/me` | DELETE | Bearer | 202 | (none) | `DeletionScheduledResponse` |
| `/me/cancel-deletion` | POST | Bearer | 200 | (none) | `CancellationResponse` |
| `/me/export` | GET | Bearer | 200 | (none) | `ExportResponse` |

---

## Swift networking sketch (URLSession + async/await)

```swift
struct AuthClient {
    let baseURL: URL
    let session: URLSession = .shared
    private let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.dateDecodingStrategy = .iso8601
        return d
    }()

    func login(email: String, password: String) async throws -> TokenPairResponse {
        let body = LoginRequest(email: email, password: password)
        var req = URLRequest(url: baseURL.appendingPathComponent("/auth/login"))
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try JSONEncoder().encode(body)

        let (data, resp) = try await session.data(for: req)
        guard let http = resp as? HTTPURLResponse else { throw URLError(.badServerResponse) }

        if (200..<300).contains(http.statusCode) {
            return try decoder.decode(TokenPairResponse.self, from: data)
        }
        // Decode RFC 7807 problem
        if let problem = try? decoder.decode(ApplicationProblem.self, from: data) {
            throw problem
        }
        throw URLError(.badServerResponse)
    }
}
```

---

## Notas adicionales iOS

1. **Token storage:** usar Keychain (`kSecClassGenericPassword`). NO `UserDefaults`.
2. **Refresh strategy:** interceptor que detecta 401 → llama `/auth/refresh` → retry una vez. Si refresh también 401 → logout local + redirect login.
3. **Idempotency-Key:** auth endpoints NO requieren (no son operaciones idempotentes per RFC 9110 §9.2.2). Otros endpoints sí (plan, food/photo, food/text) — ver D12 mobile SDK breaking changes en `docs/PROJECT_STATE.md`.
4. **Apple Sign-In nonce:** backend valida iss + aud + nonce server-side. iOS debe enviar `id_token` raw del `ASAuthorizationAppleIDCredential.identityToken`.
5. **Google Sign-In:** `id_token` del `GIDSignInResult.user.idToken.tokenString`.
6. **TLS pinning:** opcional pero recomendado prod. NSURLSession con `URLSessionDelegate.urlSession(_:didReceive:completionHandler:)`.

---

## Versionado

Backend NO usa versión en URL (`/v1/...`). Breaking changes futuros via:
- Header `API-Version: 2026-06-05` (TBD, no implementado)
- Deprecated fields marcados en OpenAPI con `deprecated: true`
- Soft deprecation window mínimo 1 release

OpenAPI live: `GET /docs` (Swagger UI) — gated en prod, abierto en dev.

---

**Doc generado:** 2026-06-05 post i18n feature ship.
**Owner contact:** Miguel Saravia.

---

# Apéndice — FAQ iOS engineer (2026-06-05)

## A1. ¿`GET /me` existe?

**SÍ.** Vive en **profile context**, no identity (`app/profile/presentation/router.py:52`).

```
GET /me  →  ProfileResponse  (requiere Bearer)
```

`fetchAndSetCurrentUser` funciona desde día 1. iOS modela `ProfileResponse`, NO confundir con auth `User`.

### `ProfileResponse` schema completo

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
  "medical_conditions": ["diabetes_t2"],
  "other_condition": null,
  "allergies": ["dairy"],
  "other_allergy": null,
  "country": "PE",
  "region": "latam",
  "locale": "es",
  "theme": "light",
  "onboarding_completed": true,
  "updated_at": "2026-06-05T14:30:00Z"
}
```

### Swift mapping `ProfileResponse`

```swift
enum Sex: String, Codable { case male, female }
enum Units: String, Codable { case metric, imperial }
enum Goal: String, Codable {
    case weightLoss = "weight_loss"
    case maintain
    case muscleGain = "muscle_gain"
    case weightGain = "weight_gain"
    case health
}
enum ActivityLevel: String, Codable {
    case sedentary
    case lightlyActive = "lightly_active"
    case moderatelyActive = "moderately_active"
    case veryActive = "very_active"
    case extraActive = "extra_active"
}
enum Theme: String, Codable { case light, dark }

struct ProfileResponse: Codable {
    let userId: UUID
    let name: String?
    let age: Int?
    let sex: Sex?
    let units: Units
    let weightKg: Decimal?
    let heightCm: Decimal?
    let goal: Goal?
    let activityLevel: ActivityLevel?
    let medicalConditions: [String]
    let otherCondition: String?
    let allergies: [String]
    let otherAllergy: String?
    let country: String?
    let region: String?
    let locale: String        // Field acepta {"es","en","pt","fr","de"} (DB legacy). Runtime i18n SOLO traduce a {"es","en"} — otros fallback "es".
    let theme: Theme
    let onboardingCompleted: Bool
    let updatedAt: Date?

    enum CodingKeys: String, CodingKey {
        case userId = "user_id"
        case name, age, sex, units
        case weightKg = "weight_kg"
        case heightCm = "height_cm"
        case goal
        case activityLevel = "activity_level"
        case medicalConditions = "medical_conditions"
        case otherCondition = "other_condition"
        case allergies
        case otherAllergy = "other_allergy"
        case country, region, locale, theme
        case onboardingCompleted = "onboarding_completed"
        case updatedAt = "updated_at"
    }
}
```

### Otros endpoints `/me/*` (profile context)

| Endpoint | Method | Body | Response |
|----------|--------|------|----------|
| `/me` | GET | (none) | `ProfileResponse` |
| `/me` | PATCH | `ProfilePatch` (todos opcionales) | `ProfileResponse` |
| `/me/onboarding` | POST → 201 | `OnboardingRequest` | `ProfileResponse` |
| `/me/locale` | GET | (none) | `LocaleResponse` (`{"locale":"es"}`) |
| `/me/locale` | PATCH | `LocalePatch` (`{"locale":"en"}`) | `LocaleResponse` |

⚠️ **`PATCH /me` NO acepta `locale`.** Body con `locale` → 422 `extra_forbidden`. Usa `PATCH /me/locale` dedicado.

⚠️ **Colisión de path:** `GET /me` = profile, `DELETE /me` = identity GDPR. Mismo path, distinto método. iOS debe routear por verbo HTTP, no por path.

### `OnboardingRequest` — contract crítico

Min required: `age`, `sex`, `weight_kg`, (`height_cm` O `height_m`), `goal`, `activity_level`, `dietary_pattern`.

Constraints:
- `age: 18-80` (pediatric <18 y geriatric >80 REFUSED)
- `weight_kg: 30-250`
- `height_cm: 120-240` O `height_m: 1.20-2.40`
- `bodyfat_pct: 3-60` (opcional, activa Cunningham BMR)
- `medical_conditions: max 6 items` (closed enum `MobileCondition`)
- `allergies: max 7 items` (closed enum `MobileAllergen`)

Hard-stops validación server:
- `other_allergy` non-empty → 422 `urn:nova:problem:plan:allergen-unmapped-requires-review`
- `pregnancy` sin `trimester` → 422 `trimester_required_for_pregnancy`
- `lactation` sin `is_exclusively_breastfeeding` → 422 `breastfeeding_status_required_for_lactation`
- Sin `height_cm` ni `height_m` → 422 `height_required`

Closed enums iOS:
```swift
enum MobileCondition: String, Codable {
    case diabetesT2 = "diabetes_t2"
    case hypertension
    case celiac
    case dyslipidemia      // UI chip "Colesterol alto"
    case hypothyroidism
    case lactation
    case pregnancy
}

enum MobileAllergen: String, Codable {
    case dairy, gluten
    case treeNuts = "tree_nuts"
    case shellfish, egg, soy
}

enum DietaryPattern: String, Codable {
    case omnivore, pescatarian, vegetarian, vegan
}

enum Trimester: String, Codable { case first, second, third }
```

---

## A2. ¿`POST /auth/password/reset` existe?

**NO.** Reset password = flujo OTP, NO endpoint dedicado.

**iOS NO deshabilitar ForgotPassword UI.** Wire al flujo OTP `purpose="reset"`:

### Flujo reset (2 calls)

```
1. POST /auth/otp/send
   { "email": "user@x.com", "purpose": "reset" }
   → 202 { "status": "sent" }

2. POST /auth/otp/verify
   { "email": "user@x.com", "purpose": "reset", "code": "123456" }
   → 200 TokenPairResponse
```

Tokens devueltos = nueva sesión activa.

⚠️ **Verificar lado backend:** confirmar con owner si `VerifyOtp(purpose="reset")` realmente rota password o solo emite tokens. Si es lo segundo, UX iOS debería decir "Inicia sesión sin contraseña" en vez de "Restablece contraseña" (más honesto).

### Swift wrap UI ForgotPassword

```swift
func resetPasswordFlow(email: String, code: String) async throws -> TokenPairResponse {
    // Step 1
    try await authClient.sendOtp(email: email, purpose: .reset)
    // (UI prompts user for code)
    // Step 2
    return try await authClient.verifyOtp(email: email, purpose: .reset, code: code)
}
```

---

## A3. ¿Otros paths `/v1/plan/*`, `/v1/logs/*` migran?

**NO.** Backend NUNCA usó prefix `/v1/`. Routes son bare.

**Tabla actual paths real:**

| Context | Paths bare |
|---------|-----------|
| identity | `/auth/register`, `/auth/login`, `/auth/oauth/{provider}`, `/auth/refresh`, `/auth/logout`, `/auth/otp/send`, `/auth/otp/verify`, `/me` (DELETE), `/me/cancel-deletion`, `/me/export` |
| profile | `/me` (GET/PATCH), `/me/onboarding`, `/me/locale` (GET/PATCH) |
| plan | `/plans`, `/plans/active`, `/plans/{plan_id}/advance`, `/plans/{plan_id}/meals/{meal_id}/swap` |
| tracking food | `/logs/food/*` |
| vision | `/logs/food/photo` |
| voice | `/logs/food/text` |
| coach | `/chat`, `/chat/stream` |

**Sin T9 migration. iOS apunta direct.**

⚠️ **Doc debt:** `docs/PROJECT_STATE.md` líneas 55-59 dice `POST /v1/plan/generate`, `POST /v1/plan/me/recalibrate`, etc. **INCORRECTO.** Paths reales son `/plans*`. Phase 2 agent también notó que `recalibrate` endpoint no existe en plan router. Owner debe corregir tabla PROJECT_STATE.md.

⚠️ **Si owner quiere `/v1/` versioning futuro:** introducir AHORA antes de público breaking ramp. Post-launch = más cara la migración.

---

## A4. ¿`AuthUser.id` tipo? `String` o `UUID`?

**UUID.** Backend serializa `uuid.UUID` Python como string RFC 4122.

### Wire JSON
```json
{ "user_id": "550e8400-e29b-41d4-a716-446655440000" }
```

### Swift Codable
```swift
struct TokenPairResponse: Codable {
    let accessToken: String
    let refreshToken: String
    let tokenType: String
    let userId: UUID         // ✅ Swift decodifica RFC 4122 auto

    enum CodingKeys: String, CodingKey {
        case accessToken = "access_token"
        case refreshToken = "refresh_token"
        case tokenType = "token_type"
        case userId = "user_id"
    }
}
```

`ProfileResponse.user_id` también `UUID` — consistente backend-wide. iOS modela TODOS los `user_id` como `Swift.UUID`, no `String`.

**Mismatch resuelto:** `AuthUser.id: UUID` en iOS. Eliminar cualquier `String` ID handling existente.

---

## Resumen accionable iOS (post-FAQ)

| # | Pregunta | Status backend | Acción iOS | Bloqueante día 1? |
|---|----------|---------------|------------|---------|
| 1 | `GET /me` | ✅ profile context | Modelar `ProfileResponse`. `fetchAndSetCurrentUser` → GET /me. | NO |
| 2 | `POST /auth/password/reset` | ❌ NO existe | ForgotPassword wire flujo OTP `purpose=reset` (2 calls). NO deshabilitar UI. | NO |
| 3 | `/v1/*` prefix | ❌ NO existe ni migra | Sin prefix. Doc PROJECT_STATE.md líneas 55-59 mal. Apunta direct. | NO |
| 4 | `AuthUser.id` tipo | UUID | Swift `UUID` nativo. Eliminar `String` ID handling. | NO |

Cero blockers iOS día 1. Cero T9 migration. Cero UI deshabilitar. Cero mismatch tipo.
