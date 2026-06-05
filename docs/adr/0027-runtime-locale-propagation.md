# ADR-0027 — Runtime locale propagation (Accept-Language → response)

- Status: Accepted
- Date: 2026-06-05
- Deciders: owner (Miguel), base Claude (product/architect synthesis), team agents (Phase 1-8)
- Extends: ADR-0007 (i18n strategy — EN canonical IDs + translation layer)
- Supersedes: hardcoded `locale="es"` fallback in `app/plan/application/create_plan.py:203`

## Context

ADR-0007 locked EN canonical IDs (ENUMs, columns, JSON keys) and per-locale display strings via `i18n_translations(scope, key, locale, value)` table + per-row `*_translations jsonb` columns. It did NOT specify HOW request-time locale resolves at runtime, leaving each context free to invent its own fallback (`profile.locale or "es"` proliferated in plan + nutrition + recipes).

By session 2026-06-05 the divergence created concrete bugs:

1. `create_plan.py:203` hardcoded `"es"` fallback even when caller had a valid `Accept-Language` header.
2. Coach SSE stream had `locale: str` loose typing → mypy strict gap + risk of unsupported locale leaking to LLM prompt.
3. Errors RFC 7807 responses were EN-only — Spanish-speaking user got English error titles, breaking UX.
4. OTP emails ignored `Accept-Language` entirely → anonymous signup always Spanish regardless of device locale.
5. Water_view (sesión 2026-06-05) shipped correct locale-aware pattern but as one-off; no shared abstraction.

## Decision

1. **Single locale resolution chain** for every user-facing response:
   `Accept-Language` header > `profile.locale` (when user authenticated) > `"es"` (LatAm-first default).

2. **MVP supported locales: `{es, en}`**. PT/FR/DE remain in ADR-0007 catalog seed (allergens/conditions/etc.) but NO templates, NO error translations, NO email templates shipped. Unsupported header → fallback to `"es"`. Re-evaluation post-1k paying users.

3. **Shared module `app/shared/i18n/`** owns resolution:
   - `locale_resolver.py` — pure functions: `parse_accept_language`, `resolve_locale`, `resolve_email_locale` (D5 variant: profile wins over header for emails)
   - `translator.py` — `Translator` class reading `i18n_translations` with Redis cache (TTL 3600s) + fallback chain
   - `fastapi_dep.py` — `LocaleDep = Annotated[Locale, Depends(get_locale)]`
   - All modules except `fastapi_dep.py` are framework-agnostic (no FastAPI imports) per Clean Architecture mandate.

4. **`Locale = Literal["es", "en"]`** single source of truth. `SUPPORTED_LOCALES` derived via `get_args(Locale)`. mypy strict everywhere.

5. **Translation source split (KISS/DRY)**:
   - **DB-backed via `Translator`** for: error messages (`scope="error"`), validation messages (`scope="validation"`), closed vocabularies inherited from ADR-0007 (allergens, conditions, goals, activity levels, meal times).
   - **Inline `_MESSAGES` dict literal** at module level for: hot-path templates (water_view, coach intents, plan rationale where applicable) — pattern established by `app/plan/domain/water_view.py:_MESSAGES`. Module constant, immutable, O(1) lookup, zero DB cost.

6. **Recipe localization** reuses existing `Recipe.translated_name(locale) / translated_description(locale) / translated_instructions(locale)` (`app/recipes/domain/entities.py:67-73`). NO duplication. Plan presentation reads tuple `(name_en, name_translations, desc_en, desc_translations)` directly (avoids hydrating full `Recipe` aggregate for response projection).

7. **Layer L1-L4 plan ranking stays canonical EN**. Translation happens ONLY in presentation layer. Domain/application layers manipulate IDs.

8. **Errors RFC 7807**: `type` URI MUST remain EN (machine-readable identifier, RFC 7807 spec compliance). Only `title` + `detail` translated. Exception handlers read `Accept-Language` header directly (FastAPI handlers can't use `Depends` — handlers parse header via `resolve_locale(header, profile_locale=None)`; NO profile DB lookup on error path to avoid 5xx amplification).

9. **OTP emails (`SendOtp` use case)**: locale resolved at presentation layer (router). `EmailSender` Protocol stays transport-only (locale-agnostic). `_STRINGS: dict[OtpPurpose, dict[Locale, dict[str, str]]]` matrix in `app/identity/infrastructure/email_templates.py`. NO new `templates/` dir, NO jinja2.

10. **Async worker locale propagation**: `Arq` jobs (e.g. `generate_plan_task`) receive `locale` in payload — `Accept-Language` header is unavailable post-enqueue. Router resolves locale at request time, passes through `enqueue_job(..., locale=locale)`.

## Translations sourced from `i18n_translations` (seed strategy)

- Single script `scripts/seed_i18n_errors.py` seeds ES + EN simultaneously. Idempotent UPSERT `ON CONFLICT (scope, key, locale) DO UPDATE`. Re-executable safe.
- Hook in `entrypoint.sh` AFTER `alembic upgrade head`. Runs on every container start.
- Adding PT/FR/DE post-MVP = add rows to dict in script, re-run. Zero schema change.

## Logs / audit / webhooks — explicitly NOT translated

- Logs stay EN (DevOps reads in EN; `scripts/pii_log_grep.py` baseline preserved).
- Audit trail EN-anchored per ADR-0007 (compliance, EN-canonical identifiers).
- Webhook payloads (Stripe, MercadoPago, FCM) stay EN (machine-to-machine; vendor docs EN).

## Caching

- `Translator` uses Redis SET with TTL 3600s, key `i18n:{scope}:{key}:{locale}`.
- Cache miss sentinel `"\x00"` prevents repeated DB hits on absent keys (negative cache).
- Translator instance lives on `app.state.translator` (FastAPI lifespan). Single shared instance. No per-request DB call after warm-up.
- Cache hit rate target ≥95% in steady state.
- Latency overhead i18n <2ms p99 per endpoint.

## Race conditions

- `_MESSAGES` dicts are module-level immutable constants. NO mutable shared state. NO locks needed.
- Redis SET is atomic per command. Translator cache writes are race-tolerant (last-write-wins, no read-modify-write).
- Seed script UPSERT atomic at Postgres row level.

## Type safety

- `Locale = Literal["es", "en"]` enforced via mypy strict. Module-level `SUPPORTED_LOCALES: Final[frozenset[Locale]] = frozenset(get_args(Locale))`.
- All public callables take `Locale`, not `str`.
- Translator return type guaranteed `str` (fallback chain always terminates).

## Consequences

### Positive

- One resolution chain, applied uniformly across every user-facing surface (plan, coach, recipes, errors, emails).
- Scalable: adding a locale = INSERT rows + add dict entries. No code change in resolution layer.
- No new framework dependency (`Babel`, `i18next`, `gettext` rejected — overkill for 2 locales).
- Type-safe: locale at type level prevents bugs like "user sends `Accept-Language: zh` → silent crash".
- Cost-controlled: cache TTL 3600s + negative cache sentinel = ≤1 DB read per (scope,key,locale) per hour. Negligible.
- Race-free: immutable dicts + atomic Redis ops + idempotent Postgres UPSERT.
- Clean Architecture preserved: domain stays framework-agnostic, only `fastapi_dep.py` couples to FastAPI.

### Negative

- Two translation sources (DB vs inline dict) — slight cognitive overhead. Mitigation: documented decision rule (errors/vocabs → DB; hot-path templates → inline dict).
- FastAPI exception handlers cannot use `LocaleDep` (FastAPI limitation) — handlers parse header directly. Acceptable: handlers already have `Request`. No profile lookup on error path (deliberate scope reduction).
- Async worker requires explicit locale propagation in payload (no implicit request context). Documented in plan_tasks signature.

### Risks + mitigations

| Risk | Mitigation |
|------|------------|
| Cache stale after translation edit | TTL 3600s acceptable; manual `i18n:*` flush via `redis-cli` if urgent. |
| Accept-Language parser crash on malformed input | Hypothesis property-based test (300 examples) verifies parser never raises. |
| Format kwargs XSS in HTML email | `_has_balanced_braces` validator rejects malformed templates; HTML escape via stdlib `html.escape` on kwargs. |
| Scope creep (agent adds PT) | Plan §3 non-goals explicit; QA Phase 8 gate enforces. |

## Out of scope

- Frontend / mobile UI translations (CLAUDE.md GR#3 — backend only).
- Logs / audit / webhook translation (compliance reasons).
- New languages beyond `{es, en}` (D2 lock until ≥1k paying users).
- Babel / gettext / i18next (overkill for 2 locales).
- New DB tables (reuse `i18n_translations` from migration 0001).
- Schema migrations (zero needed).

## References

- ADR-0007 — i18n strategy (canonical EN IDs + translation layer)
- Plan doc: `docs/handoff/2026-06-05-i18n-runtime-locale-propagation-plan.md`
- RFC 7231 §5.3.5 — Accept-Language header semantics
- RFC 7807 — Problem Details for HTTP APIs (type URI EN-only)
- CLAUDE.md GR#3 — backend nutrition tracker scope
- CLAUDE.md non-negotiable engineering principles 1, 2, 3, 4, 7 (domain layer framework-agnostic, decimal precision, tz-aware datetimes, type hints + mypy strict, property-based tests)

## Implementation phases (executed sessions 2026-06-05)

| Phase | Owner agent | Status |
|-------|------------|--------|
| 1 — shared/i18n foundation | nova-python-expert | ✅ shipped |
| 2 — plan localization | nova-nutrition-backend-architect | ✅ shipped (with GR#0 incident, files re-applied) |
| 3 — coach template parity | nova-python-expert | in progress |
| 4 — errors RFC 7807 i18n | nova-api-expert | in progress |
| 5 — OTP email locale | nova-nutrition-backend-architect | in progress |
| 6 — docs (this ADR + CONTEXT.md update) | base Claude | ✅ shipped |
| 7 — full suite + property tests | nova-elite-test-engineer | pending |
| 8 — QA verdict | nova-qa-elite | pending |
