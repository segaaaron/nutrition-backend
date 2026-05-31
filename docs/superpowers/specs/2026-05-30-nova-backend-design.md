# NOVA Nutrition — Backend Design Spec

- Date: 2026-05-30
- Status: Approved for implementation planning
- Source of truth: `NOVA — Especificación Funcional v1.0` (HTML) + architect agents under `.claude/agents/`

## 1. Goal

Build the backend for NOVA — Neural Nutrition AI: a multi-platform nutrition assistant (iOS/Android/Web, LatAm + US). Backend must outperform Fitia via verified DB, proactive AI coach, dynamic recipes, and dynamic metabolic recalibration.

## 2. Decisions (locked)

| Topic | Choice |
|---|---|
| Language / runtime | Python 3.12 + FastAPI (async) |
| Architecture | Modular Monolith — Clean Architecture + DDD per bounded context |
| ORM / migrations | SQLAlchemy 2 (async) + Alembic |
| DB image | `timescale/timescaledb-ha:pg16` (Timescale + pgvector + Postgres) |
| Cache / broker | Redis 7 |
| Workers | Arq (async, Redis-backed) |
| AI provider | OpenAI (`gpt-4o-2024-08-06` vision, `gpt-4o-mini` coach+plan L4, `whisper-1` STT, `text-embedding-3-large` 1536-dim) |
| Auth | Own JWT (RS256) + refresh + Google/Apple OAuth + email OTP |
| Image compression | `pyvips` (libvips) + `pillow-heif` for iOS HEIC |
| Image storage | Deferred (URL field nullable; Firestore/Firebase to be added later) |
| Deploy | Dokploy via `docker-compose.yml` |
| Observability | OpenTelemetry + Sentry + Prometheus `/metrics` |
| Scope | MVP + AI (vision, coach, STT) |
| Payments | Stripe (US/CA/EU) + Mercado Pago (LatAm) |
| **Language strategy** | **EN canonical IDs + i18n display layer** (locales: `en`, `es`, `pt`, `fr`, `de`). Reverses earlier round-2 ES-canonical decision. |
| Multi-region catalog | `recipes.regions[]` + 14-allergen superset (US+EU). Regions: `us`, `ca`, `eu`, `uk`, `latam`. |
| **Target VPS** | **Hostinger KVM 2 — 8 GB RAM / 100 GB NVMe / 2 vCPU** (tunable up to Contabo/Hetzner later — see §23). |

## 3. Service topology (4 containers)

```
api      FastAPI/uvicorn — REST + SSE
worker   Arq — vision IA, image compression batch, plan generation, embeddings, recalibration
db       timescale/timescaledb-ha:pg16 (timescaledb + vector + pgcrypto + pg_trgm + unaccent)
redis    redis:7-alpine — cache, broker, rate limit, pubsub for SSE
```

## 4. Layered structure (per bounded context)

```
app/<context>/
  domain/          entities, value objects, domain events, ports (Protocols)
  application/     use cases, DTOs, orchestration
  infrastructure/  SQLAlchemy repos, OpenAI client, Arq tasks, external adapters
  presentation/    FastAPI routers, Pydantic schemas, dependencies
```

Domain layer has zero framework imports. Infrastructure depends on domain. Presentation depends on application.

## 5. Bounded contexts

1. `identity` — JWT auth, Google/Apple OAuth, email OTP, refresh tokens
2. `profile` — user, biometrics, allergies, conditions, preferences, units
3. `nutrition` — BMR/TDEE/macros/hydration computation, kcal range, dynamic metabolic recalibration
4. `recipes` — recipes (Composition Pattern), verified foods catalog, semantic search via pgvector
5. `plan` — Plan/DayPlan/MealPlan, lifecycle state machine (day/week/month), generation, swap
6. `tracking` — FoodLog (6 methods), water, weight, fasting, daily goals, grocery list
7. `coach` — IA chat streaming (SSE), proactive suggestions, meal swap intent
8. `gamification` — streaks, achievements, celebrations
9. `imaging` (shared infra) — pyvips compression, HEIC decode, EXIF strip

Cross-cutting: `core/` (config, logging, DI, errors, in-process event bus), `shared/` (common VOs, unit conversions).

## 6. Domain — key value objects & invariants

- `Calories(int, 500..8000)`
- `MacroBreakdown(p, c, g)` — must satisfy `kcal == p*4 + c*4 + g*9 ± 2%` (current catalog audit deviation is 0 kcal; tolerance is strict on purpose). The same `2%` constant is reused by the catalog ingest gate (§20) and the QA suite. Single source of truth: `app/shared/domain/macro_tolerance.py::MACRO_TOLERANCE = 0.02`.
- `Kg(decimal, 20..300)`, `Cm(decimal, 50..250)`
- `KcalRange(min, max)` — `max - min == 200` (UI shows range, not single value — adherence improvement vs Fitia)
- `ActivityFactor(decimal in {1.20, 1.375, 1.55, 1.725, 1.90})`
- `MifflinStJeor.compute(sex, weight_kg, height_cm, age) -> Calories`
- `Locale` — `Literal['en','es','pt','fr','de']`. Default `en`. Derived from `Accept-Language` header when absent on the user record.
- `Region` — `Literal['us','ca','eu','uk','latam']`. Derived from `user_profiles.country` via the `regions` table (`countries[]` lookup). Drives recipe catalog filtering and allergen subset.

## 7. Database schema (PostgreSQL + Timescale + pgvector)

Extensions: `timescaledb`, `vector`, `pgcrypto`, `pg_trgm`, `unaccent`.

### Identity
```sql
users(id uuid pk, email citext unique, password_hash text null,
      oauth_provider text null, oauth_subject text null,
      email_verified bool, created_at timestamptz, last_login_at timestamptz,
      -- GDPR/LGPD soft-delete (ADR-0005). Hard delete via background job after 30d grace.
      deletion_requested_at timestamptz null,
      deleted_at timestamptz null);

-- Refresh token family / reuse-detection (ADR aligned; OAuth2 RFC 6819 §5.2.2.3).
refresh_tokens(id uuid pk,
               user_id uuid not null references users(id) on delete cascade,
               token_hash text,
               family_id uuid not null,
               parent_id uuid null references refresh_tokens(id) on delete cascade,
               expires_at timestamptz, revoked_at timestamptz,
               reused_at timestamptz null);
CREATE INDEX ON refresh_tokens(family_id);
-- Reuse semantics: if a token with revoked_at IS NOT NULL is presented at /auth/refresh,
-- set reused_at=now() and revoke every row sharing its family_id.

otp_codes(user_id uuid not null references users(id) on delete cascade,
          code_hash text,
          purpose enum('register','reset','login'),
          expires_at timestamptz, attempts int,
          locked_until timestamptz null);
-- Lockout policy: 5 consecutive failed attempts on a single (user_id, purpose) row
-- set locked_until = now() + interval '15 minutes'. Verify endpoint MUST 423 while locked.
```

### Profile
```sql
user_profiles(user_id uuid primary key references users(id) on delete cascade,
              name text, age int check(12<=age<=100),
              sex enum('male','female'),
              units enum('metric','imperial'),
              weight_kg numeric(5,2), height_cm numeric(5,2),
              goal enum('weight_loss','maintain','muscle_gain','weight_gain','health'),
              activity_level enum('sedentary','lightly_active','moderately_active','very_active','extra_active'),
              medical_conditions text[],  -- canonical EN ids (see ADR-0001 Appendix A revised)
              other_condition text,
              allergies allergen_enum[],  -- typed array; closed vocab
              other_allergy text,
              country char(2),            -- ISO-3166-1 alpha-2
              region char(5),             -- derived from country via regions table
              locale char(2),             -- 'en'|'es'|'pt'|'fr'|'de'
              theme enum('light','dark'),
              updated_at timestamptz);
CREATE INDEX ON user_profiles(region);
CREATE INDEX ON user_profiles(locale);
```

### Nutrition (derived goals + history)
```sql
nutritional_goals(id uuid pk,
                  user_id uuid not null references users(id) on delete cascade,
                  kcal_min int, kcal_max int,
                  protein_g int, carbs_g int, fat_g int, water_ml int,
                  bmr int, tdee int, activity_factor numeric(4,3),
                  reason enum('onboarding','weight_change','goal_change','plateau','manual'),
                  valid_from timestamptz, valid_to timestamptz null,
                  created_at timestamptz);
-- Exactly one row per user with valid_to IS NULL (current); others historical.
CREATE UNIQUE INDEX one_current_goals
    ON nutritional_goals(user_id) WHERE valid_to IS NULL;
CREATE INDEX ON nutritional_goals(user_id, valid_from DESC);
```

### Recipes
```sql
-- Foods: per-100g canonical nutrition. EN canonical column names.
foods(id uuid pk,
      name_en text not null, name_norm text not null,  -- normalised for trigram search
      name_translations jsonb not null default '{}',   -- {locale: localised_name}
      brand text, country char(2),
      portion_g numeric, kcal numeric,
      protein_g numeric, carbs_g numeric, fat_g numeric,
      fiber_g numeric, sugar_g numeric, sodium_mg numeric, sat_fat_g numeric,
      micronutrients jsonb,
      barcode text unique null,
      verified bool default false, source text,
      embedding vector(1536));
CREATE INDEX ON foods USING hnsw (embedding vector_cosine_ops)
    WITH (m = 32, ef_construction = 200);
CREATE INDEX ON foods USING gin (name_norm gin_trgm_ops);
CREATE INDEX ON foods(barcode) WHERE barcode IS NOT NULL;

-- Closed allergen vocabulary (ADR-0001, round-3: 14-item US+EU superset).
-- Declared BEFORE recipe_allergens so the FK column can reference the enum type.
-- US top-9 (FALCPA 2023): dairy, gluten, tree_nuts, peanuts, shellfish, fish, egg, soy, sesame.
-- EU additions (EU 1169/2011 Annex II): celery, mustard, lupin, sulphites, molluscs.
CREATE TYPE allergen_enum AS ENUM (
    'dairy','gluten','tree_nuts','peanuts','shellfish','fish','egg','soy','sesame',
    'celery','mustard','lupin','sulphites','molluscs'
);

recipes(id uuid pk,
        -- i18n: EN canonical + per-locale display fields.
        name_en text not null,
        name_translations jsonb not null default '{}',          -- {es: '...', pt: '...', ...}
        description_en text,
        description_translations jsonb not null default '{}',
        image_url text null,
        kcal int, protein_g int, carbs_g int, fat_g int,
        -- Aggregated micros for clinical filters: diabetes uses sugar_g,
        -- hypertension uses sodium_mg, dyslipidaemia uses sat_fat_g.
        -- Recomputed by sync_recipe_aggregates() on recipe_components mutation.
        fiber_g int not null default 0,
        sugar_g int not null default 0,
        sodium_mg int not null default 0,
        sat_fat_g int not null default 0,
        tags text[],
        meal_time enum('breakfast','lunch','dinner','snack'),
        prep_min int,
        instructions_en text[],
        instructions_translations jsonb not null default '{}',
        verified_by text,
        -- Provenance (lets us quarantine a bad LLM batch later).
        source_batch text null,
        source_catalog text null,                               -- e.g. 'nova_seed_v1', 'usda_fdc'
        -- Multi-region targeting: filter candidate recipes by user's region.
        regions char(5)[] not null default '{}',                -- subset of regions.code
        -- Denormalised allergen list for fast NOT(allergens && $1) filtering.
        -- Source of truth remains recipe_allergens; trigger keeps this column in sync.
        allergens allergen_enum[] not null default '{}',
        embedding vector(1536),
        created_at timestamptz);

CREATE INDEX ON recipes USING gin (regions);
CREATE INDEX ON recipes USING gin (allergens);
CREATE INDEX ON recipes USING gin (tags);
CREATE INDEX ON recipes(meal_time);
CREATE INDEX ON recipes(source_batch) WHERE source_batch IS NOT NULL;

recipe_components(id uuid pk,
                  recipe_id uuid not null references recipes(id) on delete cascade,
                  food_id uuid null references foods(id) on delete restrict,
                  sub_recipe_id uuid null references recipes(id) on delete restrict,
                  amount_g numeric, modifier text, position int);
CREATE INDEX ON recipe_components(recipe_id);
CREATE INDEX ON recipe_components(food_id) WHERE food_id IS NOT NULL;
-- Composition Pattern: recipes compose foods + sub-recipes + modifiers.

recipe_allergens(recipe_id uuid not null references recipes(id) on delete cascade,
                 allergen allergen_enum not null,
                 primary key (recipe_id, allergen));

-- Denormalisation rule (finding #27).
-- Source of truth = recipe_allergens. App code MUST NOT write recipes.allergens directly;
-- only this trigger updates the cached array. Plan generation reads recipes.allergens
-- (with an array-overlap GIN index) for the allergen hard-exclude filter (§9.5).
CREATE OR REPLACE FUNCTION sync_recipe_allergens()
    RETURNS trigger
    LANGUAGE plpgsql
    SECURITY DEFINER
AS $$
DECLARE
    affected_recipe uuid;
BEGIN
    -- Statement-level fires once per statement; consolidate via transition tables.
    -- For row-level usage (simpler), we recompute for the affected recipe_id.
    IF TG_OP = 'DELETE' THEN
        affected_recipe := OLD.recipe_id;
    ELSE
        affected_recipe := NEW.recipe_id;
    END IF;

    UPDATE recipes
       SET allergens = COALESCE((
            SELECT array_agg(allergen ORDER BY allergen)
              FROM recipe_allergens
             WHERE recipe_id = affected_recipe
       ), '{}'::allergen_enum[])
     WHERE id = affected_recipe;

    RETURN NULL;
END;
$$;

CREATE TRIGGER trg_sync_recipe_allergens
    AFTER INSERT OR UPDATE OR DELETE ON recipe_allergens
    FOR EACH ROW EXECUTE FUNCTION sync_recipe_allergens();

-- Aggregated micros (finding #7). Sums components × (foods.* per 100g) × cantidad_g/100.
-- For sub-recipe components, recurse one level (sub-recipes themselves are already
-- aggregated). Same source-of-truth contract as allergens: app code never updates the
-- cached columns directly.
CREATE OR REPLACE FUNCTION sync_recipe_aggregates()
    RETURNS trigger
    LANGUAGE plpgsql
    SECURITY DEFINER
AS $$
DECLARE
    affected_recipe uuid;
BEGIN
    affected_recipe := COALESCE(NEW.recipe_id, OLD.recipe_id);

    UPDATE recipes r
       SET fiber_g   = COALESCE(agg.fiber,    0),
           sugar_g   = COALESCE(agg.sugar,    0),
           sodium_mg = COALESCE(agg.sodium_mg,0),
           sat_fat_g = COALESCE(agg.sat_fat,  0)
      FROM (
          SELECT
              SUM(f.fiber_g    * rc.amount_g / 100.0)::int AS fiber,
              SUM(f.sugar_g    * rc.amount_g / 100.0)::int AS sugar,
              SUM(f.sodium_mg  * rc.amount_g / 100.0)::int AS sodium_mg,
              SUM(f.sat_fat_g  * rc.amount_g / 100.0)::int AS sat_fat
            FROM recipe_components rc
            JOIN foods f ON f.id = rc.food_id
           WHERE rc.recipe_id = affected_recipe
      ) agg
     WHERE r.id = affected_recipe;

    RETURN NULL;
END;
$$;

CREATE TRIGGER trg_sync_recipe_aggregates
    AFTER INSERT OR UPDATE OR DELETE ON recipe_components
    FOR EACH ROW EXECUTE FUNCTION sync_recipe_aggregates();

-- HNSW index tuning. Recall@10 ≥ 0.95 gated in tests/perf/test_vector_recall.py.
CREATE INDEX ON recipes USING hnsw (embedding vector_cosine_ops)
    WITH (m = 32, ef_construction = 200);
-- NB: allergens is allergen_enum[] so the type system already pins the closed vocab;
-- no CHECK constraint required.
```

### i18n + region support tables (round-3)

```sql
-- Per-locale display strings for closed vocabularies (allergens, conditions, goals, etc).
-- Read by the presentation layer keyed by (scope, key, Accept-Language locale).
i18n_translations(scope text not null,         -- 'allergen'|'condition'|'goal'|'meal_time'|'ui_label'|'activity_level'
                  key text not null,           -- canonical EN id (e.g. 'tree_nuts', 'weight_loss')
                  locale char(2) not null,     -- 'en'|'es'|'pt'|'fr'|'de'
                  value text not null,
                  updated_at timestamptz default now(),
                  primary key (scope, key, locale));
CREATE INDEX ON i18n_translations(scope, locale);

-- Lexicon: ingredient (normalised, locale-tagged) → allergen tag.
-- Used by catalog ingest gate 5 and by the manual food-log NLP parser.
ingredient_allergens(ingredient_norm text not null,
                     allergen allergen_enum not null,
                     locale char(2) not null,
                     primary key (ingredient_norm, allergen, locale));
CREATE INDEX ON ingredient_allergens(allergen);

-- Synonym collapse table for medical condition tokens fed by upstream LLM batches.
condition_synonyms(synonym text primary key,
                   canonical text not null,    -- maps to ADR-0001 Appendix A code
                   reason text);

-- Region metadata: drives recipe filtering and locale defaults.
regions(code char(5) primary key,              -- 'us'|'ca'|'eu'|'uk'|'latam'
        name text not null,
        allergen_set allergen_enum[] not null, -- effective allergen subset for that region
        countries char(2)[] not null,          -- ISO-3166-1 alpha-2 list belonging to this region
        default_locale char(2) not null);
CREATE INDEX ON regions USING gin (countries);
```

Seed rows for `regions` (loaded by migration 0001):

| code | allergen_set | countries | default_locale |
|---|---|---|---|
| `us` | 9 US FALCPA top-9 | `{US}` | `en` |
| `ca` | 11 (US-9 + mustard, sulphites) | `{CA}` | `en` |
| `eu` | 14 (full superset) | `{DE,FR,IT,ES,PT,NL,BE,…}` | `en` (override per country via `i18n_translations`) |
| `uk` | 14 (full superset) | `{GB}` | `en` |
| `latam` | 9 US FALCPA top-9 | `{MX,PE,CO,AR,CL,BR,VE,EC,UY,PY,BO,CR,PA,GT,HN,SV,NI,DO,PR}` | `es` (`pt` for BR) |

### Plan
```sql
plans(id uuid pk,
      user_id uuid not null references users(id) on delete cascade,
      type enum('day','week','month'),
      total_days int, current_day int,
      status enum('active','completed','cancelled'),
      goal text, meals_per_day int, preferences text[],
      kcal_target int,
      -- Optimistic-locking version for the state machine (§9.3).
      version int not null default 0,
      created_at timestamptz);
CREATE UNIQUE INDEX one_active_plan ON plans(user_id) WHERE status='active';
CREATE INDEX ON plans(user_id, created_at DESC);

plan_days(id uuid pk,
          plan_id uuid not null references plans(id) on delete cascade,
          day_index int, date date, completed bool);
CREATE INDEX ON plan_days(plan_id, day_index);

plan_meals(id uuid pk,
           plan_day_id uuid not null references plan_days(id) on delete cascade,
           meal_time enum('breakfast','lunch','dinner','snack'),
           recipe_id uuid null references recipes(id) on delete restrict,
           kcal int, protein_g int, carbs_g int, fat_g int,
           water_ml int, water_pct numeric, completed bool,
           swapped_from uuid null);
CREATE INDEX ON plan_meals(plan_day_id);
```

### Tracking
```sql
food_logs(id uuid pk,
          user_id uuid not null references users(id) on delete cascade,
          date date,
          meal_time enum('breakfast','lunch','dinner','snack'),
          food_id uuid null references foods(id) on delete restrict,
          recipe_id uuid null references recipes(id) on delete restrict,
          free_text_name text null,
          amount_g numeric, kcal int, protein_g int, carbs_g int, fat_g int,
          method enum('photo','voice','text','barcode','search','manual'),
          confidence numeric(4,3) null, source_image_url text null,
          -- Idempotency-Key support (§8). Hash retained 24h, then NULLed by job.
          idempotency_key text null,
          -- Prompt provenance for vision/text-parse paths.
          prompt_sha256 text null,
          created_at timestamptz);
CREATE INDEX ON food_logs(user_id, date DESC);
CREATE INDEX ON food_logs(user_id, date, meal_time);
CREATE UNIQUE INDEX one_log_per_idem_key
    ON food_logs(user_id, idempotency_key) WHERE idempotency_key IS NOT NULL;

-- Timescale hypertables. FK to users for cascade; hypertable chunks inherit it.
water_logs(time timestamptz,
           user_id uuid not null references users(id) on delete cascade,
           ml int, target_ml int);
SELECT create_hypertable('water_logs','time');
CREATE INDEX ON water_logs(user_id, time DESC);

weight_logs(time timestamptz,
            user_id uuid not null references users(id) on delete cascade,
            weight_kg numeric,
            body_fat_pct numeric null, waist_cm numeric null, photo_url text null);
SELECT create_hypertable('weight_logs','time');
CREATE INDEX ON weight_logs(user_id, time DESC);

-- Continuous aggregate: biometric_aggregates_daily (14d / 30d rolling means)

fasting_sessions(id uuid pk,
                 user_id uuid not null references users(id) on delete cascade,
                 method_h int check(method_h in (16,18,20)),
                 start_ts timestamptz, end_ts timestamptz null,
                 duration_s int null, target_s int, achieved bool);
CREATE INDEX ON fasting_sessions(user_id, start_ts DESC);

daily_goals(user_id uuid not null references users(id) on delete cascade,
            date date,
            item enum('breakfast','lunch','dinner','water'),
            completed bool, auto bool, completed_at timestamptz,
            primary key(user_id,date,item));

grocery_lists(id uuid pk,
              plan_id uuid not null references plans(id) on delete cascade,
              generated_at timestamptz);
grocery_items(id uuid pk,
              list_id uuid not null references grocery_lists(id) on delete cascade,
              category enum('fruits_vegetables','proteins','dairy','pantry','other'),
              name text, amount text, purchased bool);
CREATE INDEX ON grocery_items(list_id);

-- Progress photos (ADR-0005 lists this table in the hard-delete cascade).
progress_photos(id uuid pk,
                user_id uuid not null references users(id) on delete cascade,
                taken_at timestamptz not null,
                weight_kg numeric null,
                image_url text null,
                blurhash text null,
                created_at timestamptz not null default now());
CREATE INDEX ON progress_photos(user_id, taken_at desc);
```

### Gamification
```sql
streaks(user_id uuid not null references users(id) on delete cascade,
        type enum('daily','fasting','protein'),
        value int, last_day date, primary key(user_id,type));
achievements(user_id uuid not null references users(id) on delete cascade,
             code text, unlocked_at timestamptz,
             primary key(user_id,code));
```

### Coach
```sql
coach_conversations(id uuid pk,
                    user_id uuid not null references users(id) on delete cascade,
                    title text, locale char(2) not null default 'en',
                    created_at timestamptz);
CREATE INDEX ON coach_conversations(user_id, created_at DESC);
coach_messages(id uuid pk,
               conv_id uuid not null references coach_conversations(id) on delete cascade,
               role enum('user','assistant','system'),
               content text, tokens_in int, tokens_out int,
               -- Prompt provenance (finding #30; mirrors food_logs.prompt_sha256).
               -- 64-char hex SHA256 of the rendered system+user prompt at call time.
               prompt_sha256 text null,
               created_at timestamptz);
CREATE INDEX ON coach_messages(prompt_sha256) WHERE prompt_sha256 IS NOT NULL;
```

`coach_messages.conv_id` cascade-deletes when a conversation is removed, so the
ADR-0005 erasure chain `users → coach_conversations → coach_messages` runs in
one statement against `users`.

### Audit
```sql
audit_log(id bigserial pk, ts timestamptz default now(),
          user_id uuid null references users(id) on delete set null,
          actor_type enum('user','system','admin'),
          action text, target_type text, target_id text, metadata jsonb);
-- Append-only; row-level revoke of UPDATE/DELETE.
-- GDPR/LGPD note (ADR-0005): audit_log is the **only** owned table that does NOT cascade
-- on user delete. Instead the FK uses ON DELETE SET NULL so the row survives as a
-- pseudonymised security/fraud trace (24-month retention, legitimate-interest basis).
-- Every other table referencing users(id) cascades hard, matching the ADR-0005 list.
```

### AI / ops / determinism support
```sql
-- Prompt versioning + kill-switch (finding #13).
ai_prompts(id uuid pk, name text not null, version int not null,
           body text not null, model text not null,
           params jsonb not null default '{}'::jsonb,
           active bool not null default false,
           -- Provenance / governance (finding #13 round 2).
           description text null,
           updated_by uuid null references users(id) on delete set null,
           created_at timestamptz default now());
CREATE UNIQUE INDEX one_active_prompt_per_name
    ON ai_prompts(name) WHERE active = true;

feature_flags(key text primary key, enabled bool not null default false,
              rollout_pct int not null default 0 check(rollout_pct between 0 and 100),
              payload jsonb not null default '{}'::jsonb,
              description text null,
              updated_by uuid null references users(id) on delete set null,
              updated_at timestamptz default now());
-- Canonical keys: vision.enabled, coach.enabled, recalibration.enabled,
--                 cost_cap.global_kill, plans.snack_slot.

-- Deterministic plan generation (finding #23).
plan_generation_seeds(plan_id uuid primary key references plans(id) on delete cascade,
                      seed bigint not null);

-- Short-lived SSE tickets for browser EventSource (finding #19). TTL = 30s.
coach_sse_tickets(token_hash text primary key,
                  user_id uuid not null references users(id) on delete cascade,
                  conv_id uuid not null references coach_conversations(id) on delete cascade,
                  expires_at timestamptz not null);
CREATE INDEX ON coach_sse_tickets(expires_at);
-- Cleanup (finding #29): Arq cron `cleanup_expired_sse_tickets` runs every 5 minutes:
--   DELETE FROM coach_sse_tickets WHERE expires_at < now();
-- Emits `sse_tickets_expired_total` counter; see §13.
```

### Cascade & retention policy (summary — finding #28)

Every table owned by a `users.id` row above carries an explicit
`REFERENCES users(id) ON DELETE CASCADE` (directly or transitively through a
parent like `plans → plan_days → plan_meals`, `coach_conversations →
coach_messages`, `grocery_lists → grocery_items`). The single exception is
`audit_log`, which uses `ON DELETE SET NULL` to preserve a pseudonymised
security trace for 24 months per ADR-0005 §"Audit-log retention exception".
Hard-delete of a `users` row is therefore one statement; no application-level
fan-out is required.

The cascade chain is enforced by integration test
`tests/compliance/test_gdpr_erasure_cascade.py::test_all_owned_tables_cascade_on_user_delete`
which inserts one row per owned table for a synthetic user, deletes the user,
and asserts `count(*) = 0` on each (and `count(*) = N, user_id IS NULL` on
`audit_log`).

## 8. REST API (maps spec §13)

```
# Auth
POST   /auth/register
POST   /auth/login
POST   /auth/oauth/{google|apple}
POST   /auth/otp/send
POST   /auth/otp/verify
POST   /auth/refresh
POST   /auth/logout

# Profile + goals
GET    /me
PATCH  /me
DELETE /me                        # GDPR/LGPD erasure request → 202 {scheduled_for}
POST   /me/cancel-deletion        # abort during 30d grace → 200 {cancelled:true}
GET    /me/export                 # data portability → 200 {download_url} (signed, 24h)
POST   /me/onboarding
GET    /me/targets
GET    /me/targets/history
GET    /me/locale
PATCH  /me/locale
GET    /i18n/{scope}                # ?locale=es — cached 5 min

# Plans
POST   /plans
GET    /plans/active
POST   /plans/{id}/advance
POST   /plans/{id}/meals/{mid}/swap
PATCH  /plans/{id}/meals/{mid}/complete
GET    /plans/{id}/grocery-list

# Recipes & foods
GET    /recipes
GET    /recipes/{id}
POST   /recipes/search/semantic
GET    /foods
GET    /foods/barcode/{ean}

# Food logging (6 methods)
POST   /logs/food                 # manual / search / barcode
POST   /logs/food/text            # NLP parser
POST   /logs/food/voice           # audio -> STT -> parser
POST   /logs/food/photo           # 202 -> job
GET    /logs/food/jobs/{jobId}    # SSE / poll
POST   /ai/recognize              # internal alias
DELETE /logs/food/{id}

# Trackers
POST   /logs/water
POST   /logs/weight
GET    /logs/weight/trend

POST   /fasting/start
POST   /fasting/{id}/stop
GET    /fasting/active
GET    /fasting/history

GET    /goals/today
POST   /goals/today/{item}/toggle

GET    /progress
POST   /progress/photo

# Gamification
GET    /gamification/streak
GET    /gamification/achievements

# Coach
POST   /coach/sse-ticket          # returns {ticket, expires_in} for browser EventSource
POST   /coach/chat                # SSE stream (Authorization: Bearer  OR  ?ticket=<one-shot>)
GET    /coach/conversations
GET    /coach/conversations/{id}/messages

# Images (internal)
POST   /images/compress

# Admin (RBAC: admin role only; rejects on non-admin JWT with 403)
POST   /admin/ai-prompts                  # publish new prompt version (see policy below)
PATCH  /admin/ai-prompts/{id}             # activate / deactivate a version
POST   /admin/feature-flags/{key}         # upsert flag
PATCH  /admin/feature-flags/{key}         # update enabled / rollout_pct / payload
```

**AI prompt promotion policy.** A `POST /admin/ai-prompts` payload MUST carry
an `evaluation` block referencing an eval-set hash and the result it produced
(e.g. `{eval_set_sha256, brier_score, item_precision, item_recall, kcal_mae}`).
The endpoint refuses to mark a prompt `active=true` unless the eval result
meets the thresholds in ADR-0003 (Brier ≤ 0.20 for vision) and the AI eval
gates in `tests/clinical/test_vision_calibration_brier.py`. Activation flips
the partial unique index `one_active_prompt_per_name`; the previously-active
row is auto-deactivated in the same transaction.

Auth: Bearer JWT (RS256, 15min) + opaque rotating refresh.
Rate limit (Redis sliding window): 60/min user, 5/min `/ai/*`, 10/min `/auth/*`.
OpenAPI auto + ReDoc at `/docs`.

### i18n contract (round-3)

- Every request MAY carry an `Accept-Language: <BCP-47>` header. The server
  collapses it to a supported `Locale` (`en`, `es`, `pt`, `fr`, `de`) via the
  `match_locale(accept_lang) -> Locale` resolver. If the header is missing the
  user's `user_profiles.locale` is used; if still null, the user's region's
  `regions.default_locale`; if still null, `en`.
- `GET /me/locale` → `{"locale":"es"}`.
- `PATCH /me/locale` body `{"locale":"pt"}` → 200, updates `user_profiles.locale`.
- Responses returning catalog content (recipes, foods, conditions, allergens,
  goals) include localised display strings via the `i18n_translations` table.
  Identifier fields (`meal_time`, `goal`, allergen codes, condition codes) are
  always returned as EN canonical IDs; the client renders them through the
  bundled translation map or the on-demand `GET /i18n/{scope}?locale=` endpoint.
- `GET /i18n/{scope}?locale=` (cached 5 min in Redis) → `{key: localised_value}`
  for `scope ∈ {allergen, condition, goal, meal_time, activity_level, ui_label}`.

### Region auto-detect

On profile creation/update, the API derives `user_profiles.region` from
`country` using `regions.countries` (`SELECT code FROM regions WHERE $country = ANY(countries)`).
If `country` is null or unknown → `region := 'us'` (safest allergen-disclosure
default — US FALCPA top-9). The derived region drives plan generation candidate
filtering (§9.5) and the effective allergen subset surfaced to the UI.

### GDPR/LGPD erasure response contracts (finding #31)

- `DELETE /me` → `202 Accepted`, body
  `{"status":"scheduled","scheduled_for":"<ISO-8601 UTC, now+30d>"}`. Idempotent:
  a second call within the grace returns the same `scheduled_for`.
- `POST /me/cancel-deletion` → `200 OK`, body `{"cancelled":true}`. Clears
  `users.deletion_requested_at`. `409 Conflict` if no deletion is pending or
  if the grace already elapsed (`410 Gone`, account already hard-deleted).
- `GET /me/export` → `200 OK`, body `{"download_url":"<signed-url>","expires_at":"…"}`.
  The blob is async-generated by `worker.export_user_data_task`; the URL is
  signed for 24 h and points at the export object store path
  (Firestore/Firebase bucket once that backend lands; local FS for MVP).

### Idempotency
All mutating endpoints listed below accept an `Idempotency-Key: <client-uuid>` header.
The server stores `SHA256(user_id || endpoint || key)` in Redis for 24h with the original
response payload. Replays within the window return the original `2xx` response and the
header `Idempotent-Replayed: true`. Required on:
- `POST /logs/food`, `POST /logs/food/text`, `POST /logs/food/voice`, `POST /logs/food/photo`
- `POST /logs/water`, `POST /logs/weight`
- `POST /plans`
- `POST /fasting/start`
For `POST /logs/food*` the key is **also** persisted on the row via
`food_logs.idempotency_key` (`one_log_per_idem_key` partial unique index) so the
guarantee survives Redis eviction.

## 9. Critical flows

### 9.1 Photo → kcal
1. `POST /logs/food/photo` accepts HEIC/JPEG.
2. API persists raw bytes temporarily (local FS for MVP; storage backend pending).
3. Enqueues Arq task `vision_recognize(image_id, user_id, meal_time)`.
4. Returns `202 {jobId}`.
5. Worker:
   - `pyvips` decode (HEIC via `pillow-heif`) → resize 1024px → JPEG q=85 buffer.
   - OpenAI `gpt-4o` vision with system prompt + strict JSON schema:
     `{items:[{name, estimated_amount_g, kcal, protein_g, carbs_g, fat_g, confidence}]}`.
   - For each item: trigram + embedding lookup in `foods`. Match if `confidence > 0.7`.
   - Insert `food_logs(method='photo', confidence=…)`.
   - Publish `FoodLogged` event → handlers (daily_goals, streak).
   - Notify client via Redis pubsub `user:{id}` → SSE.

### 9.2 Dynamic metabolic recalibration
Triggered by `WeightLogged`. Formal contract — see ADR-0002 for the rationale.

Inputs (last 14d):
- `weights = [(day_index, weight_kg)]` (require `len(weights) >= 7`, else **skip**).
- `kcal_in[14d]` daily intake series from `food_logs`.
- `tdee_current` from the current `nutritional_goals` row.

Pre-processing (ADR-0002 §"Edge cases" — single-day measurement noise):
- Before slope regression, **winsorise** the 14-day `weight_kg` series at the
  5th / 95th percentiles of the window: every value below P5 is clamped to
  P5; every value above P95 is clamped to P95. This kills single-day spikes
  from scale-calibration error or fluid swings without dropping data. OLS
  runs on the winsorised series.

Definitions:
- `weights_w = winsorise(weights, p_low=0.05, p_high=0.95)`.
- `slope_kg_per_day = OLS_linear_regression(weights_w).slope`  (ordinary least
  squares of `weight_kg` against `day_index`).
- `observed_tdee_inferred = mean(kcal_in[14d]) - slope_kg_per_day * 7700`.
- `mifflin_recalc = MifflinStJeor(sex, weight_kg_now, height_cm, age) * activity_factor`.
- `tdee_new = round( 0.5 * mifflin_recalc + 0.5 * observed_tdee_inferred )`
  clamped to `tdee_current ± 15%`.
- `expected_kg_per_day = (mean(kcal_in[14d]) - tdee_current) / 7700`.
- `delta_ratio = slope_kg_per_day / expected_kg_per_day` (skip if `|expected_kg_per_day| < 1e-4`).

Trigger (all must hold):
1. `|delta_ratio - 1| > 0.5`.
2. `n_days >= 14`.
3. `days_since_last_recalibration >= 14`  (cool-down to prevent oscillation).

On trigger:
- Expire current `nutritional_goals` row (`valid_to = now()`).
- Insert new row with new TDEE, derived macros and water target,
  `reason='plateau' | 'weight_change'`.
- Publish `GoalsRecalibrated`.

Edge cases (covered by tests, see ADR-0002):
- Athlete bulk: positive slope expected → no trigger if `goal='muscle_gain'`
  and `delta_ratio ∈ [0.7, 1.5]`.
- Post-partum / illness markers: feature-flag `recalibration.enabled` per user can
  pause until cleared.
- Insufficient data (`< 7` weight points in 14d): skip silently, emit
  `recalibration_skipped_total{reason="insufficient_data"}`.

### 9.3 Plan lifecycle (state machine)

Formal transition table (finding #17). The domain entity `Plan.advance(event)`
is the **only** path that mutates `plans.status` or `plans.current_day`; any
other write raises `IllegalTransition` (409, §11).

| from | event | guard | to | side effects |
|---|---|---|---|---|
| `active` | `MealCompleted` | not all meals done | `active` | mark `plan_meals.completed=true`, update `daily_goals` |
| `active` | `DayCompleted` | `all_meals_completed` AND `current_day < total_days` AND `type != 'day'` | `active` (`current_day++`) | streak +1, `daily_goals` row closed |
| `active` | `DayCompleted` | `all_meals_completed` AND `current_day == total_days` AND `type != 'day'` | `completed` | celebration event, CTA `newplan` |
| `active` | `DayCompleted` | `all_meals_completed` AND `type == 'day'` | `active` | flag `regenerate_tomorrow`, streak +1 |
| `active` | `UserCancelled` | — | `cancelled` | revoke active plan unique index slot |
| `completed` / `cancelled` | any | — | — | `IllegalTransition` |

Optimistic locking: `plans.version` is incremented on every transition;
`Plan.advance` accepts `expected_version` and raises `ConflictError` (409) on
mismatch. Property test
`tests/unit/domain/plan/test_state_machine.py::test_illegal_transitions_raise`
enumerates the Cartesian product `(from_state × event)` and asserts every
unlisted cell raises `IllegalTransition`.

### 9.4 Coach SSE streaming
1. `POST /coach/chat` returns `text/event-stream`.
2. Load conv + last 10 messages + system prompt (profile + goals + active plan + last logs).
3. OpenAI streaming → yield SSE chunks.
4. On close: persist assistant message + tokens in/out.
5. Detect intents (e.g., "intercambiar comida X") → invoke plan swap inline.

### 9.5 Plan generation
1. `POST /plans` enqueues `generate_plan_task`. The use case generates (or accepts) a
   deterministic `seed: int64` and persists it in `plan_generation_seeds`. The seed
   feeds every RNG call in the pipeline (shuffle, tie-breaking, slot ordering) so the
   same `(profile_snapshot, catalog_version, seed)` triple yields byte-identical plans.
   Re-generation accepts an optional `seed` body field to reproduce a user-reported plan.
2. Select recipes: **hard-exclude by allergies** using the closed `allergen_enum` and the
   denormalised `recipes.allergens` array (`NOT (recipes.allergens && $allergies)`);
   **hard-filter by region** (`recipes.regions && ARRAY[$user_region]::char(5)[]`);
   filter by goal + meal_time + tag preferences; filter contra-indicated conditions.
3. Seeded shuffle + embedding similarity score against profile vector.
4. Per-day macro balancing: `sum(kcal) ∈ kcal_target ± 5%`, `protein >= goal * 0.95`.
5. **Repetition cap** (deterministic, applies to `type in ('week','month')`):
   - At most **2** occurrences of the same `recipe_id` in **any rolling 7-day window**.
   - For `type='month'`: additionally at most **4** occurrences of the same recipe in the
     full 30-day plan (prevents the same dish appearing every Monday).
   - For `type='day'`: rule does not apply.
6. Persist `plans` + `plan_days` + `plan_meals`.
7. Expand grocery list asynchronously.

## 10. Image compression (`app/imaging/`)

### Domain port
```python
class ImageCompressor(Protocol):
    async def compress(self, raw: bytes, *, profile: CompressionProfile) -> CompressedImage: ...
```

### Profiles
```python
class CompressionProfile(Enum):
    MEAL_PHOTO = ("webp", 82, 1024)
    PROGRESS   = ("avif", 60, 1600)
    THUMBNAIL  = ("webp", 70, 400)
    AVATAR     = ("webp", 80, 512)
```

### Infrastructure
```python
import pyvips, pillow_heif
pillow_heif.register_heif_opener()

class VipsImageCompressor:
    async def compress(self, raw, *, profile):
        fmt, q, max_dim = profile.value
        img = pyvips.Image.new_from_buffer(raw, "", access="sequential")
        img = img.autorot()
        for f in img.get_fields():
            if f.startswith("exif-"):
                img.remove(f)
        scale = min(1.0, max_dim / max(img.width, img.height))
        if scale < 1.0:
            img = img.resize(scale)
        out = img.write_to_buffer(f".{fmt}[Q={q},strip]")
        return CompressedImage(bytes=out, format=fmt, w=img.width, h=img.height)
```

Sync compression on upload (<200ms for 4MP). Batch / heavy → Arq task.
Requires apt deps in `api.Dockerfile`: `libvips42`, `libheif1`.

### EXIF strip verification (mandatory CI gate)
After `write_to_buffer(..., strip)`, re-parse the **output bytes** with `exifread`
and assert:
- No key starts with `GPS` (latitude/longitude/altitude/timestamp).
- No `Image Make`, `Image Model`, `Image Software`, `Exif DateTimeOriginal` tags.
- `Image Orientation` may remain (already applied via `autorot()`).

Implementation: `VipsImageCompressor.compress()` calls `_assert_exif_stripped(out)`;
the helper raises `EXIFLeakError` if any disallowed key survives, surfacing as a 500
to fail-closed rather than silently store a GPS-leaking blob. Test fixture
`tests/integration/imaging/test_exif_strip.py` feeds an image with deliberate GPS
EXIF and asserts the post-compress buffer has zero `GPS*` keys across every
`CompressionProfile`.

## 11. Errors

- Domain hierarchy (`app/core/errors.py`):
  - `DomainError`
    - `ValidationError` → HTTP 400 / 422 (Pydantic)
    - `NotFoundError` → 404
    - `ConflictError` → 409
    - `GoneError` → 410 (used by `POST /me/cancel-deletion` when grace elapsed)
    - `LockedError` → 423 (OTP locked, §7 `otp_codes.locked_until`)
    - `BusinessRuleViolation` → 422
    - `IllegalTransition` → 409 (plan state machine §9.3)
    - `RateLimited` → 429 (Redis sliding window, §8)
    - `CostCapExceeded` → 429 (per-user/per-org cap, §12 + ADR-0004)
    - `AuthError`
      - `Unauthenticated` → 401 (no/expired/bad JWT)
      - `AuthTicketInvalid` → 401 (SSE ticket missing/expired/already-consumed)
      - `Forbidden` → 403
    - `UpstreamError` → 502 / 503 (OpenAI 5xx, DB pool exhausted)

- Full HTTP status map emitted by this spec, every code wired to a translator
  in `app/core/errors.py::problem_for(exc)`:

  | HTTP | Emitter / cause |
  |---:|---|
  | 200 | success (GET / cancellation / export URL) |
  | 201 | resource created (POST /plans, POST /logs/food*) |
  | 202 | async accepted (DELETE /me, POST /logs/food/photo) |
  | 204 | no content (PATCH /me/onboarding step ack, DELETE /logs/food/{id}) |
  | 400 | malformed request (JSON parse, schema) |
  | 401 | `Unauthenticated`, `AuthTicketInvalid` |
  | 403 | `Forbidden` |
  | 404 | `NotFoundError` (incl. IDOR-safe negative) |
  | 409 | `ConflictError`, `IllegalTransition`, `one_active_plan` violation |
  | 410 | `GoneError` (grace elapsed; tombstoned account) |
  | 422 | `BusinessRuleViolation`, Pydantic validation |
  | 423 | `LockedError` (OTP brute-force lockout) |
  | 429 | `RateLimited` (rate limit) **and** `CostCapExceeded` (cost cap) |
  | 500 | unhandled (Sentry-paged), `EXIFLeakError` (fail-closed) |
  | 502 | `UpstreamError` from OpenAI / external |
  | 503 | DB / Redis unavailable; `cost_cap.global_kill.enabled` short-circuit |

- Global FastAPI handler → RFC 7807 `application/problem+json` with stable
  `type` URIs (`https://nova-nutrition.com/errors/<slug>`) per subclass.
- Structlog JSON logs with `request_id`, `user_id`, `trace_id`.

## 12. Security

- argon2id for password hashing.
- JWT RS256 with key rotation (`kid` header).
- CORS allowlist.
- PII at rest (medical conditions, progress photos): `pgcrypto` `PGP_SYM_ENCRYPT`.
- Rate limit via Redis sliding window.
- Strip EXIF on every uploaded image (GPS privacy).
- Secure response headers.
- Body size limit 10 MB for image endpoints.
- Strict Pydantic (no `extra=allow`).
- Secrets via Dokploy env vars; nothing in repo.
- `audit_log` table append-only for health-data access.

### OpenAI cost cap (ADR-0004)
- **Per-user daily hard cap**: USD 1.50 by default (≈150 vision calls or ≈30k coach
  output tokens). Tracked in Redis sorted set keyed by `cost:{user_id}:{yyyymmdd}`,
  TTL 48h. Each OpenAI call increments by `prompt_tokens * in_price + completion_tokens
  * out_price + image_units * image_price` (priced from a versioned constants module).
- **Per-org global daily cap**: configurable via `feature_flags.cost_cap.global_kill`
  payload `{ "usd_daily": <float> }`. When exceeded, every `/ai/*` and `/coach/*`
  endpoint returns 429 with body `{detail:"daily_cost_cap_exceeded"}` and headers
  `Retry-After`, `X-Cost-Limit-Reset` (epoch seconds at next UTC midnight).
- **Alarms**: page at 80% of either cap; kill-switch flag `cost_cap.global_kill.enabled`
  short-circuits every AI call to 503 instantly (no deploy required).

### SSE auth ticket (finding #19)
- Browser EventSource cannot set `Authorization`. Flow:
  1. Client `POST /coach/sse-ticket` with bearer JWT → server inserts
     `coach_sse_tickets(token_hash=SHA256(ticket), user_id, conv_id, expires_at=now()+30s)`
     and returns `{ticket, expires_in: 30}`.
  2. Client opens `EventSource("/coach/chat?ticket=<ticket>")`.
  3. Server hashes the query-string ticket, looks it up, **deletes the row** (one-shot),
     and only then opens the stream. Expired/missing ticket → 401 before any AI call.
- Mobile clients keep using `Authorization: Bearer`. JWTs MUST NOT appear in
  request-path query strings (compliance: server log scrubber strips `?ticket=` value).

### Secrets / key rotation
- JWT signing keys live on disk via Dokploy secret mounts; `kid` header on every token;
  active+previous key pair held in memory; rotation runbook in `docs/ops/jwt-rotation.md`
  (to be authored before first prod deploy).
- OpenAI key rotated quarterly; rotation procedure documented in same ops folder.

## 13. Observability

- OpenTelemetry SDK + OTLP exporter (configurable).
- `/healthz` liveness, `/readyz` readiness (checks db + redis).
- Sentry SDK FastAPI integration.
- Prometheus `/metrics`: request latency p50/p95/p99, OpenAI token usage, Arq queue depth.
- Required counters (committed by the fix-round patches):
  - `cost_cap_blocked_total{cap="user"|"org"}` (ADR-0004).
  - `sse_tickets_issued_total`, `sse_tickets_consumed_total`,
    `sse_tickets_expired_total` (finding #29 cleanup job).
  - `recalibration_skipped_total{reason}` (ADR-0002).
  - `idempotency_replay_total{endpoint}` (§8 Idempotency).
  - `catalog_audit_gate_failed_total{gate}` (§20).
- Scheduled tasks (Arq cron):
  - `cleanup_expired_sse_tickets` — every 5 min;
    `DELETE FROM coach_sse_tickets WHERE expires_at < now();`. Emits
    `sse_tickets_expired_total`.
  - `hard_delete_pending_users_task` — daily, idempotent (ADR-0005).
- SLOs: p95 `/me/targets` < 80 ms; p95 non-photo `/logs/food` < 200 ms; p95 vision job < 8 s.

## 14. Testing

- `tests/unit/domain/` — VOs, Mifflin formulas, recipe composition, macro balance.
- `tests/unit/application/` — use cases with in-memory repos.
- `tests/integration/` — pytest + testcontainers (real Timescale, Redis).
- `tests/contract/` — schemathesis over OpenAPI.
- `tests/e2e/` — onboarding → plan → logs → recalibration.
- `tests/clinical/` — ADR-driven clinical-safety harness:
  - `test_recalibration_blend.py` (ADR-0002 — OLS slope + winsorisation + blend)
  - `test_vision_calibration_brier.py` (ADR-0003 — `confianza` Brier ≤ 0.20)
- `tests/security/` — security & cost gates:
  - `test_cost_cap_kill_switch.py` (ADR-0004 — 429 on user/org cap, 503 on kill)
- `tests/compliance/` — GDPR/LGPD:
  - `test_gdpr_erasure_cascade.py` (ADR-0005 — every owned table cascades)
- `tests/data/` — catalog ingest gates (`test_catalog_ingest_gates.py`,
  one test per gate from §20; catalog-ingest spec is the authority) and
  `test_multi_region_filtering.py` (asserts plan-gen only returns recipes
  whose `regions[]` overlaps the user's region; asserts US-region users never
  receive recipes tagged `eu`-only when allergens differ).
- `tests/i18n/` — `test_translation_completeness.py`: every canonical key in
  closed scopes (`allergen`, `condition`, `goal`, `meal_time`,
  `activity_level`) MUST have a translation row in every supported locale
  (`en, es, pt, fr, de`). Missing rows fail the test with a structured diff.
  Asserts `i18n_translations` is closed-over-canonical-set per scope.
- `tests/perf/` — `test_vector_recall.py` (HNSW recall@10 ≥ 0.95),
  pytest-benchmark baselines per endpoint SLO.
- factory-boy fixtures.
- mutmut mutation tests over `nutrition/domain` and `plan/domain`.
- Coverage gates: domain 90%, application 80%, total 75%.
- Load (k6): steady 100 rps + spike.

## 15. Repo layout

```
Nova-nutrition-backend/
├── app/
│   ├── core/                config, logging, di, errors, event_bus
│   ├── shared/              common VOs, unit conversions
│   ├── identity/            domain/ application/ infrastructure/ presentation/
│   ├── profile/
│   ├── nutrition/
│   ├── recipes/
│   ├── plan/
│   ├── tracking/
│   ├── coach/
│   ├── gamification/
│   ├── imaging/             ImageCompressionService (pyvips)
│   └── main.py              FastAPI app factory
├── worker/
│   └── main.py              Arq WorkerSettings + task registry
├── migrations/              Alembic
│   └── versions/0001_init.py
├── data/meals/nova_meals_catalog.json   (existing seed)
├── scripts/
│   ├── seed_foods.py
│   ├── seed_recipes.py     ingests nova_meals_catalog.json
│   └── compute_embeddings.py
├── tests/
├── docker/
│   ├── api.Dockerfile      python:3.12-slim + libvips42 + libheif1
│   ├── worker.Dockerfile
│   └── db.Dockerfile       FROM timescale/timescaledb-ha:pg16 + CREATE EXTENSION vector
├── docker-compose.yml      Dokploy entry
├── alembic.ini
├── pyproject.toml          (uv)
├── .env.example
├── .python-version
└── README.md
```

## 16. docker-compose.yml (Dokploy)

```yaml
services:
  api:
    build: { context: ., dockerfile: docker/api.Dockerfile }
    env_file: .env
    depends_on: [db, redis]
    ports: ["8000:8000"]
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
  worker:
    build: { context: ., dockerfile: docker/worker.Dockerfile }
    env_file: .env
    depends_on: [db, redis]
    command: arq worker.main.WorkerSettings
  db:
    build: { context: ./docker, dockerfile: db.Dockerfile }
    environment:
      POSTGRES_USER: nova
      POSTGRES_PASSWORD: ${DB_PASSWORD}
      POSTGRES_DB: nova
    volumes: [pgdata:/var/lib/postgresql/data]
  redis:
    image: redis:7-alpine
    volumes: [redisdata:/data]
volumes:
  pgdata: {}
  redisdata: {}
```

## 17. Environment variables (`.env.example`)

```
DATABASE_URL=postgresql+asyncpg://nova:pass@db:5432/nova
REDIS_URL=redis://redis:6379/0
JWT_PRIVATE_KEY_PATH=/secrets/jwt.pem
JWT_PUBLIC_KEY_PATH=/secrets/jwt.pub
OPENAI_API_KEY=
GOOGLE_OAUTH_CLIENT_ID=
APPLE_OAUTH_CLIENT_ID=
APPLE_OAUTH_TEAM_ID=
APPLE_OAUTH_KEY_ID=
SENTRY_DSN=
OTEL_EXPORTER_OTLP_ENDPOINT=
LOG_LEVEL=INFO
ENV=dev
```

## 18. Out of scope (deferred)

- Image storage backend (Firestore / Firebase / S3 — TBD later by user).
- Microservice split (revisit only if scale demands).
- Apple Health / Google Health Connect sync (Phase 2).
- Widgets / Apple Watch (Phase 3).
- Community / challenges (Phase 3).

## 19. Open follow-ups

- Confirm Apple OAuth flow specifics (Sign in with Apple revocation handling).
- ~~Decide cost cap policy for OpenAI per-user (token budget per day).~~ **Resolved by ADR-0004.**
- Localization corpus for `es-MX`, `es-PE`, `pt-BR`, `en-US`.
- Verified-food curation workflow (admin tooling) — likely separate spec.

## 20. Catalog ingest pipeline (overview)

Full design contract: `docs/superpowers/specs/2026-05-30-catalog-ingest-pipeline.md`.
Summary: every batch of `nova_meals_catalog.json` (or any upstream JSON) is processed
by `scripts/audit_catalog.py` before SQL touches happen. The script runs 8 ordered
data-quality gates and exits non-zero on the first failure, producing a structured
`reports/catalog_audit_<ts>.json` for CI artifacts.

| # | Gate | Pass criterion |
|---|---|---|
| 1 | JSON Schema conformance | every record validates against `schemas/catalog_record.json` |
| 2 | Macro consistency | `|kcal - (p*4+c*4+g*9)| / kcal <= 0.02` (§6 constant) |
| 3 | Allergen taxonomy (closed) | `allergens ⊆ allergen_enum` (sesame included) |
| 4 | Condition vocabulary | `conditions ⊆ canonical_conditions` AND `conditions ∩ allergen_enum == ∅` |
| 5 | Allergen completeness | ingredient lexicon (≥40 entries) finds no missing allergen tag |
| 6 | Duplicate detection | normalised-name Levenshtein > 2 between any two records |
| 7 | Outlier detection | kcal z-score ≤ 4 within each `meal_time` cluster |
| 8 | Image URL sanity | placeholder Firebase URL → set to `NULL`; non-https → reject |

The ingest path itself (`scripts/seed_recipes.py`) refuses to run unless the latest
audit report is green.

## 21. Vocabulary & i18n contract (round-3, reverts round-2 ES-canonical)

- **System identifiers** (Postgres ENUMs, column names, JSON keys in API
  responses): **English snake_case**. Rationale: clinical / regulatory codes
  (ICD-10, FALCPA, EU 1169) are English-anchored; the product targets US +
  LatAm + EU from day one and EN canonical IDs let every other locale be
  added by inserting rows in `i18n_translations` instead of altering enums.
- **Display strings** (recipe names, descriptions, instructions, UI labels,
  allergen labels, condition labels): per-locale text via
  `i18n_translations(scope, key, locale, value)` or per-row
  `*_translations jsonb` columns (recipes only).
- **External catalog inputs** (`nova_meals_catalog.json`): already EN
  canonical for identifiers; display strings may be in any language and are
  loaded into the appropriate `*_translations` slot with auto-detected
  locale (default `es` for the existing seed batch, which is Spanish-written).

**Locale resolution order** (per request):
1. `Accept-Language` header parsed to BCP-47 → first supported.
2. `user_profiles.locale`.
3. `regions.default_locale` for the user's `region`.
4. `'en'` (final fallback).

**Pluralisation**. Use ICU MessageFormat (`babel.support.Translations`) for
counted strings. Stored under `scope='ui_label'` with the ICU template as the
`value` and the key including a `.plural` suffix.

**Unit formatting per locale**:
- `metric` users (default everywhere except US): `kg`, `cm`, `ml`, `°C`.
- `imperial` users (US default): `lb`, `in`, `fl oz`, `°F`.
- Format strings come from `app/shared/units.py::format_for_locale(value, unit, locale)`.

**Closed scopes that MUST have a translation row in every supported locale**
(asserted by `tests/i18n/test_translation_completeness.py`):
`allergen` (14 keys), `condition` (25 keys, ADR-0001 Appendix A in EN),
`goal` (5 keys), `meal_time` (4 keys), `activity_level` (5 keys).

**Region filtering**. Plan generation (§9.5) hard-filters candidate recipes
by `recipes.regions && ARRAY[user_region]::char(5)[]`. Allergen disclosure UI
uses `regions.allergen_set` for the user's region as the visible checkbox set
(US users do not see `celery`/`mustard`/`lupin`/`sulphites`/`molluscs`
checkboxes unless they explicitly opt into "show EU-extended allergens").

No other code path may translate enum values — `i18n_translations` is the
single source of truth.

## 22. Snack catalog gap (blocker)

The current `data/meals/nova_meals_catalog.json` contains **0** records with
`mealtime='snack'` (audit: `{breakfast: 600, lunch: 800, dinner: 600, snack: 0}`).
The spec mandates `snack` in `meal_time` enum and `comidas_por_dia` can include
snack slots. Plans generated today with snack slots would be empty or crash.

Two mutually exclusive resolutions; **(a) is the chosen path**:

(a) **Generate ≥100 snack recipes** via `nova-clinical-nutrition-generator` before
    plan generation goes live. Recommended target: 200 (≈10% of corpus). Distribution:
    sweet, savoury, high-protein, low-kcal, kid-friendly buckets. **Round-3 update**:
    snacks MUST be emitted in EN canonical identifiers (`meal_time: 'snack'`,
    `targetGoals`, `allergens` from 14-superset) with a `regions` field. For universal
    snacks set `regions: ['us','ca','eu','uk','latam']`; for culturally specific snacks
    (e.g. Peruvian `causa`, Brazilian `pão de queijo`) tag only the applicable region(s).
    Display strings (name, description, ingredients, instructions) may be in any
    language; the ingest pipeline routes them into the appropriate
    `*_translations` slot based on detected locale.

(b) Drop `snack` from `meal_time` enum and clamp `comidas_por_dia` to `[3]` for MVP.
    Re-add snacks post-MVP when curation bandwidth exists.

**Dependency**: implementation of `POST /plans` is blocked on resolution. Tracked by
`tests/data/test_catalog_coverage.py::test_every_meal_time_has_minimum_records`
(min 100 per enum value).

### 22.5 Catalog cleanup backlog

Independent QA audit of the current `data/meals/nova_meals_catalog.json`
(2 000 records) surfaces concrete row-level defects that the ingest pipeline
(§20) will reject on the next run. Tracking here so they are not lost.

| Defect class | Count | Pipeline gate that rejects | Owner |
|---|---:|---|---|
| Dairy false negatives (ingredient indicates dairy, no `dairy` tag) | 161 | Gate 5 — ingredient lexicon | data-ops |
| Gluten false negatives | 169 | Gate 5 | data-ops |
| Purine false negatives (red meat / organ meat without `gout` contraindication) | 144 | Gate 5 + clinical rule | data-ops + clinical |
| Allergen tokens leaking into condition arrays | 26 | Gate 4 — disjointness | data-ops |
| Unknown allergen `mustard` (single row) | 1 | Gate 3 — closed enum | data-ops |
| Snack inventory | 0 / 100 required | §22.6 gate | clinical generator |

**Gating impact.** Until the affected rows are cleaned (or quarantined via
`recipes.source_batch` and excluded from generation), `POST /plans` MUST NOT
select recipes for the affected `meal_time` from a tainted batch. The plan
generation use case reads the latest `reports/catalog_audit_<ts>.json` and
filters its candidate set to recipes whose `source_batch` passed all 8 gates.

Cadence: data-ops owns this backlog and produces a weekly burn-down until the
counts reach zero. After the first clean batch lands, the ingest report becomes
the source of truth (no parallel spreadsheet).

### 22.6 Snack inventory gate (operational rule)

Until the snack inventory reaches **≥ 100** approved records (validated by the
ingest pipeline §20), `meals_per_day` is constrained at the API layer to
`∈ {1, 2, 3}`. A request with `meals_per_day == 4` is rejected with `422
BusinessRuleViolation` body `{"detail":"snack_slot_unavailable","required":100,
"have":<n>}`. When inventory crosses the threshold (asserted by a Prometheus
gauge `recipes_inventory_count{meal_time="snack"}`), the cap is raised to
`≤ 4` and the feature flag `plans.snack_slot.enabled` is flipped via the
admin-feature-flag endpoint (see §13 ops). No code deploy is required for the
flip; the API reads the gauge + flag on every plan-creation request.

## 23. VPS resource constraints (round-3)

### 23.1 Baseline target — Hostinger KVM 2

| Resource | Capacity |
|---|---|
| RAM | 8 GB |
| CPU | 2 vCPU (shared, AMD EPYC class) |
| Disk | 100 GB NVMe |
| Bandwidth | 8 TB / month |
| OS | Ubuntu 24.04 LTS |

Stack runs under Dokploy + Traefik. OS + Dokploy + Traefik footprint ≈ 700 MB
resident. Budget for the application stack is therefore ≤ 5.5 GB resident,
leaving ≈ 1.8 GB headroom for spikes (vision worker peak ≈ 750 MB per job).

### 23.2 Container resource matrix (docker-compose limits)

| Container | mem_limit | cpu_limit | Key tuning |
|---|---|---|---|
| `db` (timescale/timescaledb-ha:pg16) | **3 GB** | 1.0 | `shared_buffers=2GB`, `max_connections=75`, `work_mem=16MB`, `effective_cache_size=4GB`, `shm_size=1g`, `maintenance_work_mem=256MB`, `wal_buffers=16MB`, `random_page_cost=1.1` (NVMe) |
| `api` (FastAPI/uvicorn) | **600 MB** | 1.0 | `WEB_CONCURRENCY=2` workers, `--limit-concurrency=200`, asyncpg pool `size=15, max_overflow=10` |
| `worker` (Arq) | **1.5 GB** | 1.0 | `ARQ_MAX_JOBS=2` (vision pyvips peak ≈ 750 MB/job), `job_timeout=180s`, `health_check_interval=15s` |
| `redis` (redis:7-alpine) | **400 MB** | 0.5 | `maxmemory=300mb`, `maxmemory-policy=allkeys-lru`, `save ""` (no RDB for cache role) |
| **Total** | **5.5 GB** | 3.5 (CPU over-subscription OK on 2 vCPU host — spikes absorb) | — |

Swap: 4 GB OS swap as **safety net only**. Sustained swap activity → page
alert. Use `vm.swappiness=10` so Linux only swaps under real pressure.

### 23.3 Connection / concurrency budget

| Layer | Sized to |
|---|---|
| Postgres `max_connections` | 75 |
| API asyncpg pool | 15 + 10 overflow per worker × 2 workers = 50 max |
| Worker asyncpg pool | 8 + 5 overflow × 2 jobs = 26 max |
| Reserve | 75 − 50 − 26 = -1 → **shrink worker pool to 5 + 3 overflow** in `config.py` to leave 25 headroom for psql/migrations |

### 23.4 Bottleneck-prevention principles (apply in every PR)

1. Every FK + every WHERE column indexed; partial indexes on filtered queries; composite indexes for multi-column WHERE.
2. N+1 forbidden — every list endpoint uses `selectinload`/`joinedload`; SQLAlchemy event hook fails tests on N+1 in dev/CI.
3. Cursor pagination on every list endpoint (no `OFFSET` on large tables).
4. Redis cache for hot reads; invalidation via explicit domain events.
5. Async everywhere; CPU-bound work to Arq workers.
6. asyncpg pool sized to Postgres `max_connections` (§23.3).
7. Every POST that creates state accepts `Idempotency-Key` (§8).
8. Rate limit per endpoint (Redis sliding window): `/auth/*` 10/min, `/ai/*` 5/min, `/api/*` 60/min/user.
9. Backpressure: Arq queue depth max 100 — reject 429 if full.
10. Circuit breaker: every OpenAI call wrapped (3 fails → open 30s).

### 23.5 Upgrade signals (when to bump VPS)

Any of these sustained > 24 h triggers VPS upsizing (Hostinger KVM 4 → 16 GB / 4 vCPU, or migrate to Contabo VPS L / Hetzner CPX31):

- Resident RAM > 80% of 8 GB for > 1 h.
- 5-min load average > 1.6 (CPU > 70% on 2 vCPU).
- Arq vision queue depth > 15.
- Active monthly users > 1500.
- Postgres `pg_stat_database.numbackends` consistently > 60.
- p95 `POST /plans` latency > 1500 ms (plan-gen is CPU-bound on this host).
