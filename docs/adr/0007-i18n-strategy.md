# ADR-0007 — i18n strategy: EN canonical IDs + translation layer

- Status: Accepted
- Date: 2026-05-31
- Deciders: nova-nutrition-backend-architect, nova-qa-elite, product owner
- Supersedes: §21 of the round-2 design spec (which mandated ES canonical IDs)

## Context

Round-2 mandated Spanish snake_case for every Postgres ENUM and column name
because the founding team is LatAm. Round-3 product input changed the launch
posture to **USA + LatAm simultaneously**, with EU as a near-term target
(Stripe is enabled for US/CA/EU on day 1). Three concrete problems with
keeping ES canonical:

1. Clinical and regulatory codes the system has to cite (ICD-10, FALCPA,
   EU 1169/2011, USDA FDC nutrient IDs) are all English-anchored. Naming
   our enums in Spanish forces every interaction with those sources through
   a translation table.
2. The catalog generator (`nova-clinical-nutrition-generator`) was already
   emitting EN identifiers and the ingest pipeline §20 had to translate
   them — a moving translation seam between agent output, ingest, and DB.
3. Adding a new locale (`fr`, `de`, `pt-BR`) under the round-2 design
   required an ENUM ALTER plus a backfill plan. With per-locale display
   strings decoupled from the canonical key, adding a locale is a pure
   row-insert in `i18n_translations`.

## Decision

1. **Every system identifier is English snake_case**.
   - Postgres ENUMs: `goal`, `activity_level`, `meal_time`, `method`, `reason`,
     `type` (plan), `status` (plan), `item` (daily_goals), `category`
     (grocery_items), `sex`, `units`, `theme`, `allergen_enum` (14-item
     superset), and any future closed vocabulary.
   - Column names in EN snake_case (e.g. `weight_kg`, `meal_time`,
     `kcal_target`, `current_day`).
   - API JSON keys mirror DB column names.

2. **Display strings live in `i18n_translations(scope, key, locale, value)`**
   for closed vocabularies, and in per-row `*_translations jsonb` columns
   for open-text fields on recipes (`name_translations`,
   `description_translations`, `instructions_translations`).

3. **Locale resolution order** is fixed (one resolver in `app/core/i18n.py`):
   - `Accept-Language` header → first supported BCP-47 match.
   - `user_profiles.locale`.
   - `regions.default_locale` for the user's `region`.
   - `'en'` fallback.

4. **Supported locales (v0.1)**: `en`, `es`, `pt`, `fr`, `de`. Any new
   locale requires only translation-row inserts and a test sweep — no schema
   change.

5. **Pluralisation**: ICU MessageFormat (via Babel) stored under
   `scope='ui_label'` with `.plural` suffix on the key.

6. **Unit format per locale**:
   - `units='metric'` (default everywhere except US): `kg`, `cm`, `ml`, `°C`.
   - `units='imperial'` (US default): `lb`, `in`, `fl oz`, `°F`.
   - Formatting lives in `app/shared/units.py::format_for_locale(value, unit, locale)`.

7. **Coach locale parameter**: `coach_conversations.locale` pins the AI
   response language. The coach system prompt is rendered with the locale
   inlined ("Respond in Spanish.") to keep the prompt token-bounded.

8. **Closed-scope completeness invariant**: every canonical key in scope
   `allergen | condition | goal | meal_time | activity_level` MUST have a
   translation row in every supported locale. Enforced by
   `tests/i18n/test_translation_completeness.py`.

## Consequences

- Migration cost: one Alembic revision renames all round-2 ES columns to EN
  and inserts the 14-item allergen enum + i18n seed rows. Manageable because
  the codebase has no application code yet (we are pre-implementation).
- Catalog ingest pipeline §20 drops its EN→ES mapping step entirely — gate 1
  validates EN canonical IDs directly.
- The clinical generator agent emits EN identifiers (already its prior
  default; ADR-0007 makes it canonical, not transitional).
- Adding `it` or `ja` post-MVP is a translation-row import + a test rerun.

## Trade-offs considered

- **Keep ES canonical and store EN as alias** (round-2 plus a synonyms
  table): rejected — every regulatory citation would still go through a
  translation; clinical-AI prompts in EN would emit EN tokens we then
  re-translate before persistence; double-translation surface.
- **Mixed canonical** (allergens EN, goals ES): rejected — splits the
  mental model; lints have to know which enum is which language.
- **No closed vocabularies, free-form strings**: rejected — destroys the
  safety pillar (allergen hard-exclude only works on a closed enum).

## References

- Spec §6, §7, §8, §14, §21 (round-3 patch).
- ADR-0001 (allergen + condition vocabulary; both move to EN canonical
  alongside this ADR).
- ICU MessageFormat: https://unicode-org.github.io/icu/userguide/format_parse/messages/
- BCP-47: https://www.rfc-editor.org/rfc/bcp/bcp47.txt
