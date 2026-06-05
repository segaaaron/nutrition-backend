# Feature Plan — Runtime Locale Propagation (ES + EN)

**Date:** 2026-06-05
**Author:** Owner (Miguel) + base Claude (product/architect synthesis)
**Status:** APPROVED for delegation
**Supersedes:** Partial coach EN/ES branch — extends ADR-0007 to runtime resolution

---

## 1. Goal (1 sentence)

Cuando usuario ingresa request en ES o EN, todas las responses user-facing salen en ese idioma — determinístico, sin scope creep, con base ADR-0007 + tabla `i18n_translations` ya existente.

---

## 2. Decisiones locked (NO preguntar de nuevo)

| # | Decisión | Razón |
|---|----------|-------|
| D1 | Locale priority: `Accept-Language` header > `profile.locale` > `"es"` | RFC 7231 §5.3.5 estándar; mobile envía header auto |
| D2 | MVP locales: `{es, en}` solamente | LatAm-first + USA day-1; PT/FR/DE quedan en ADR-0007 pero NO se shipean |
| D3 | Scope traducciones: coach + plan + recipes + errors (RFC 7807 title+detail) | Surface usuario; logs/audit/webhooks/RFC7807 `type` URI siguen EN-only |
| D4 | Anon fallback: header > `"es"` | Pricing strategy LatAm-first |
| D5 | OTP / pre-onboarding rule: `profile.locale if profile exists else accept_language else "es"` | Determinístico signup vs reset |
| D6 | NO Babel / gettext / nueva dep | KISS para 2 locales |
| D7 | Tabla `i18n_translations(scope, key, locale, value)` ya existe (migration 0001:354). Usar. NO nueva tabla | DRY |
| D8 | Recipe `*_translations` JSONB ya existe + `Recipe.localized_*(locale)` (`entities.py:67`). NO duplicar | DRY |
| D9 | `_MESSAGES` patrón inline en módulo (como `water_view.py:_MESSAGES`) para mensajes hot-path; `i18n_translations` para vocabularios cerrados (allergens, conditions, goals) | KISS — sin sobre-ingeniería |
| D10 | NO refactor de código existente locale-aware (water_view, recipe entity, profile use_cases) — sólo wire + extend | Surgical |

---

## 3. Non-goals (NO crear, NO añadir)

- ❌ PT / FR / DE templates (post-MVP)
- ❌ Babel / gettext / i18next
- ❌ Nueva tabla DB (reusar existente)
- ❌ Migrations nuevas
- ❌ Refactor de water_view, recipe localization, profile locale handling existentes
- ❌ Traducción de logs, audit trail, webhook payloads
- ❌ Traducción de `type` URI en RFC 7807 (spec compliance)
- ❌ Cambios a APIs externas (Stripe, MercadoPago, OpenAI prompts internos)
- ❌ UI / frontend translations (backend-only scope per CLAUDE.md GR#3)

---

## 4. Constraints (engineering)

1. **SOLID** — `LocaleResolver` Single Responsibility; `Translator` Open/Closed (añadir locale = row, no edit); FastAPI Depends Dependency Inversion
2. **DRY** — una sola función `resolve_locale`; un solo `Translator`; un solo `LocaleDep`
3. **KISS** — parser `Accept-Language` propio ≤30 LoC (q-values básicos), zero deps
4. **Type-safe** — `Literal["es","en"]` en lugar de `str` libre; mypy strict
5. **Decimal/timezone rules** intactos (no aplican aquí, but CLAUDE.md baseline)
6. **Domain layer framework-agnostic** — translator en `app/shared/i18n/`, NO FastAPI imports en domain
7. **Property-based tests** con hypothesis para parser Accept-Language
8. **Si duda → ABORT + PREGUNTAR owner.** No improvisar scope.

---

## 5. Task breakdown (8 phases)

### Phase 1 — Shared i18n foundation

**Owner agent:** `nova-python-expert`

- **T1.1** Crear `app/shared/i18n/__init__.py` (re-exports públicos)
- **T1.2** Crear `app/shared/i18n/locale_resolver.py`:
  - `parse_accept_language(header: str | None) -> list[tuple[str, float]]` — RFC 7231 §5.3.5 q-values, robust a malformed
  - `resolve_locale(header: str | None, profile_locale: str | None) -> Literal["es","en"]` — priority D1+D4
  - `SUPPORTED_LOCALES: Final[frozenset[Literal["es","en"]]] = frozenset({"es","en"})`
  - Pure functions, sin I/O, mypy strict
- **T1.3** Crear `app/shared/i18n/translator.py`:
  - `class Translator` — `translate(scope: str, key: str, locale: Literal["es","en"], **kwargs) -> str`
  - Lee `i18n_translations` con Redis cache (TTL 3600s, key `i18n:{scope}:{key}:{locale}`)
  - Fallback chain: locale → `"es"` → key as-is (loud warning log)
  - `**kwargs` para formato (`str.format`); reject `{` no balanceados
- **T1.4** FastAPI dependency en `app/shared/i18n/fastapi_dep.py`:
  - `async def get_locale(accept_language: Annotated[str | None, Header()] = None, current_user: CurrentUserOptionalDep = None, session: SessionDep) -> Literal["es","en"]`
  - `LocaleDep = Annotated[Literal["es","en"], Depends(get_locale)]`
- **T1.5** Tests `tests/unit/shared/i18n/`:
  - `test_locale_resolver.py` — hypothesis property-based parser (max_examples=300): malformed input nunca lanza, q-values, case-insensitive, unknown locales → ignorados
  - `test_translator.py` — fallback chain, cache hit/miss, format kwargs, mismatched braces

**Acceptance:**
- mypy strict 0 errors
- ruff 0 issues
- 100% branch coverage en `locale_resolver.py`
- Property test: `∀ header. resolve_locale(header, None) ∈ {"es","en"}`
- Property test: `∀ malformed. parse_accept_language(malformed) no excepción`

**DoD:** PR no-merge sin estos checks.

---

### Phase 2 — Wire `LocaleDep` en plan presentation

**Owner agent:** `nova-nutrition-backend-architect`

- **T2.1** `app/plan/presentation/router.py`:
  - Añadir `LocaleDep` parameter a: `POST /plan/generate`, `GET /plan/active`, `POST /plan/me/advance`, `POST /plan/me/recalibrate`, `POST /plan/me/swap/{id}`
  - Reemplazar fallback hardcoded `"es"` en `_hydrate_water_view` por `locale` resuelto
- **T2.2** `app/plan/application/create_plan.py:203`:
  - Cambiar `locale=str(profile.get("locale") or "es")` → recibir `locale: Literal["es","en"]` por parámetro use case
  - Use case caller (router) pasa `LocaleDep`
- **T2.3** Recipe localization en plan response:
  - `app/plan/presentation/schemas.py` — añadir `name_localized`, `description_localized` a `MealResponse` / `RecipeRefResponse`
  - Hidratación en router: para cada recipe en plan response → `recipe.localized_name(locale)`, `recipe.localized_description(locale)`
  - **NO traducir en layer ranking L1-L4** (mantiene canonical EN per ADR-0007)
- **T2.4** Plan `rationale` traducido:
  - Mover strings rationale a `app/plan/domain/_messages.py:_RATIONALE_MESSAGES: dict[str, dict[str,str]]` (patrón water_view)
  - Función `localized_rationale(key: str, locale, **kwargs) -> str`
  - **Si rationale strings actuales no son enumerables (LLM-generated) → ABORT, preguntar owner**

**Acceptance:**
- Tests integration `tests/integration/plan/test_plan_response_locale.py`:
  - POST /plan/generate `Accept-Language: en` → response recipe names EN
  - POST /plan/generate `Accept-Language: es` → response recipe names ES
  - Sin header + profile.locale=es → ES
  - Sin header + sin profile → ES (anon fallback)
- mypy strict + ruff clean

---

### Phase 3 — Coach templates parity ES↔EN

**Owner agent:** `nova-python-expert`

- **T3.1** Audit `app/coach/application/template_responses.py` (196 LoC):
  - Listar todas keys/intents
  - Detectar ramas con sólo ES o sólo EN
  - Reportar matrix completa antes de editar
- **T3.2** Completar parity ES↔EN para todos templates faltantes
  - Tone consistent con `docs/product/COACH_TONE.md`
  - Emoji parity (sesión 2026-06-05 fix water_progress 💪 reference)
- **T3.3** Coach router (`app/coach/presentation/router.py`):
  - Añadir `LocaleDep` a endpoints `/chat`, `/chat/stream` (SSE)
  - Propagar locale a `template_responses` + LLM prompt instruction (`"Respond in {locale}."`)
- **T3.4** Tests `tests/unit/coach/test_template_parity.py`:
  - Test automático: `assert set(TEMPLATES_ES.keys()) == set(TEMPLATES_EN.keys())`
  - Cada template renderiza sin KeyError en ambos locales

**Acceptance:**
- 0 keys faltantes ES↔EN
- COACH_TONE.md compliance review
- SSE stream emite con locale correcto

---

### Phase 4 — Errors RFC 7807 i18n

**Owner agent:** `nova-api-expert`

- **T4.1** `app/core/problem_details.py`:
  - Inyectar `LocaleDep` en middleware
  - `title` + `detail` traducidos vía `Translator`
  - `type` URI **SIEMPRE EN** (RFC 7807 spec compliance)
  - Cada `ProblemDetail` raise lleva `title_key: str`, `detail_key: str | None`
- **T4.2** `BusinessRuleViolation` en `app/core/errors.py`:
  - Añadir field `i18n_key: str` (canonical EN snake_case, ej. `unsupported_locale`, `recalibration_too_soon`)
  - Resolución en presentation layer (middleware)
- **T4.3** Pydantic validation errors:
  - Hook en `RequestValidationError` handler → traducir `errors[].msg` vía `i18n_translations` scope=`validation`
- **T4.4** Sembrar `i18n_translations` con todos error keys (script `scripts/seed_i18n_errors.py`)
  - **Si owner no autoriza migración seed → translations live en código `_ERROR_MESSAGES` dict (KISS)**
  - **Pregunta owner: tabla seed o dict código?**
- **T4.5** Tests `tests/integration/test_error_locale.py`:
  - 400/401/403/404/422/429/503 → cada uno verificado en ES + EN

**Acceptance:**
- RFC 7807 spec compliance: `type` URI sin cambiar
- Todos errors user-facing traducidos
- Logs siguen EN-only (verificar grep)

---

### Phase 5 — OTP / pre-onboarding emails

**Owner agent:** `nova-nutrition-backend-architect`

- **T5.1** `app/notifications/infrastructure/resend_sender.py`:
  - Aceptar `locale: Literal["es","en"]` parameter
  - Cargar template ES o EN
- **T5.2** Email templates:
  - `app/notifications/templates/otp_signup_es.html`, `otp_signup_en.html`, `otp_reset_es.html`, `otp_reset_en.html`
  - Subject + body localizados
- **T5.3** Identity use cases (signup OTP, password reset OTP):
  - Lookup rule D5: `profile.locale if profile else accept_language else "es"`
  - Helper `app/shared/i18n/locale_resolver.py:resolve_email_locale(profile_locale: str | None, accept_language: str | None) -> Literal["es","en"]`
- **T5.4** Tests:
  - Signup anon `Accept-Language: en-US,en` → email EN
  - Password reset profile.locale=es + header=en → email ES (profile gana)
  - Sin header + sin profile → ES

**Acceptance:**
- Email render verificado (snapshot test)
- Resend client recibe locale correcto

---

### Phase 6 — Documentation

**Owner agent:** `nova-best-practices-advisor`

- **T6.1** `docs/adr/0027-runtime-locale-propagation.md`:
  - Extends ADR-0007
  - Status: Accepted
  - Decisions D1-D10
  - Tradeoffs documentados
- **T6.2** Update `docs/architecture/CONTEXT.md`:
  - Sección "Locale propagation" en glossary
- **T6.3** Update OpenAPI:
  - Documentar `Accept-Language` header en todos endpoints user-facing
- **T6.4** README badge / mention si aplica

---

### Phase 7 — Test full suite + property-based

**Owner agent:** `nova-elite-test-engineer`

- **T7.1** Suite completa: `pytest tests/ -x`
- **T7.2** Property-based tests:
  - `resolve_locale` invariants
  - `Translator` fallback chain invariants
  - Email locale resolution invariants
- **T7.3** Integration tests cross-context:
  - Flow: signup EN → onboarding ES → plan generate → coach chat
  - Cada step locale correcto independiente del previo
- **T7.4** Coverage: 100% en `app/shared/i18n/`, ≥90% en endpoints tocados
- **T7.5** mypy strict + ruff 0 errors en archivos tocados

---

### Phase 8 — QA verdict

**Owner agent:** `nova-qa-elite`

- **T8.1** Review architectural compliance:
  - ADR-0007 + ADR-0027 honored
  - SOLID/DRY/KISS audit
  - CLAUDE.md golden rules (no git, no scope creep, decimal/timezone N/A)
- **T8.2** Review test rigor:
  - Property-based coverage
  - Integration cross-context
  - Snapshot tests email
- **T8.3** Review security:
  - Accept-Language parser no header injection
  - Translator no template injection (no eval, no exec)
  - PII logs gate intacto (`scripts/pii_log_grep.py`)
- **T8.4** Performance:
  - Translator cache hit rate target ≥95% en steady state
  - Latency overhead i18n <2ms p99 por endpoint
- **T8.5** Verdict: **GO / NO-GO / GO-WITH-CAVEATS**

---

## 6. Dependencias / orden ejecución

```
Phase 1 (foundation)
  ↓
Phase 2 (plan) + Phase 3 (coach) + Phase 4 (errors) + Phase 5 (otp)  ← parallel
  ↓
Phase 6 (docs)
  ↓
Phase 7 (tests)
  ↓
Phase 8 (QA verdict)
```

Phase 1 bloquea todo (dependency). Phases 2-5 paralelas. Phase 6 después. Phase 7 + 8 secuencial al final.

---

## 7. Risk + mitigation

| Riesgo | Mitigación |
|--------|------------|
| Plan rationale strings hoy LLM-generated, no traducibles | ABORT phase 2.4, pregunta owner |
| Coach templates con ramas profundas ES-only | T3.1 audit reporta antes de editar; owner decide cuáles completar EN vs cuáles refactor |
| Accept-Language parser custom buggy con malformed input | Hypothesis property test cubre fuzz |
| Cache Redis Translator stale tras edit translation | TTL 1h aceptable; invalidación manual `i18n:*` flush si urgente |
| Email template HTML XSS por kwargs `format` | Translator rechaza `{` no balanceados + escape HTML en render |
| Scope creep (agent quiere añadir PT) | Non-goals §3 explícito; QA gate Phase 8.1 |

---

## 8. Deliverables esperados

1. Código nuevo: `app/shared/i18n/` (≤200 LoC), `app/notifications/templates/*.html` (4 files)
2. Código modificado: `create_plan.py`, plan router/schemas, coach router/templates, error handlers, resend_sender
3. Tests nuevos: ≥6 archivos (locale_resolver, translator, plan locale, coach parity, error locale, otp locale)
4. ADR-0027 nuevo
5. CONTEXT.md update
6. OpenAPI Accept-Language documentado
7. QA verdict report final

---

## 9. Out-of-scope explícito (no hacer)

- No tocar billing/Stripe/MercadoPago paths
- No tocar vision pipeline
- No tocar voice STT
- No tocar gamification
- No añadir PT/FR/DE
- No migrar DB
- No nueva dep Python
- No frontend / mobile SDK changes (mobile sólo añade `Accept-Language` header — ya lo hacen auto)

---

## 10. Ownership matrix

| Phase | Lead agent | Reviewer |
|-------|-----------|----------|
| 1 | nova-python-expert | nova-best-practices-advisor |
| 2 | nova-nutrition-backend-architect | nova-api-expert |
| 3 | nova-python-expert | nova-best-practices-advisor |
| 4 | nova-api-expert | nova-python-expert |
| 5 | nova-nutrition-backend-architect | nova-api-expert |
| 6 | nova-best-practices-advisor | — |
| 7 | nova-elite-test-engineer | — |
| 8 | nova-qa-elite | final gate |

---

**APPROVED — proceed delegation.**
