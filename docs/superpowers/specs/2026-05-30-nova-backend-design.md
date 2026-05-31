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
| AI provider | OpenAI (`gpt-4o` vision+chat, `whisper-1` STT, `text-embedding-3-large`) |
| Auth | Own JWT (RS256) + refresh + Google/Apple OAuth + email OTP |
| Image compression | `pyvips` (libvips) + `pillow-heif` for iOS HEIC |
| Image storage | Deferred (URL field nullable; Firestore/Firebase to be added later) |
| Deploy | Dokploy via `docker-compose.yml` |
| Observability | OpenTelemetry + Sentry + Prometheus `/metrics` |
| Scope | MVP + AI (vision, coach, STT) |

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
- `MifflinStJeor.compute(sexo, peso_kg, talla_cm, edad) -> Calories`

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
              nombre text, edad int check(12<=edad<=100),
              sexo enum('hombre','mujer'), unidades enum('metrico','imperial'),
              peso_kg numeric(5,2), talla_cm numeric(5,2),
              objetivo enum('bajar','mantener','ganar_musculo','ganar_peso','salud'),
              nivel_actividad enum('sedentario','ligero','moderado','activo','atleta'),
              condiciones_medicas text[], otra_condicion text,
              alergias text[], otra_alergia text,
              pais char(2), idioma char(2), tema enum('claro','oscuro'),
              updated_at timestamptz);
```

### Nutrition (derived goals + history)
```sql
nutritional_goals(id uuid pk,
                  user_id uuid not null references users(id) on delete cascade,
                  kcal_min int, kcal_max int,
                  proteina_g int, carbos_g int, grasas_g int, agua_ml int,
                  bmr int, tdee int, factor_actividad numeric(4,3),
                  motivo enum('onboarding','weight_change','goal_change','plateau','manual'),
                  vigente_desde timestamptz, vigente_hasta timestamptz null,
                  created_at timestamptz);
-- Exactly one row per user with vigente_hasta IS NULL (current); others historical.
CREATE UNIQUE INDEX one_current_goals
    ON nutritional_goals(user_id) WHERE vigente_hasta IS NULL;
```

### Recipes
```sql
foods(id uuid pk, nombre text, nombre_norm text, marca text, pais char(2),
      porcion_g numeric, kcal numeric, p numeric, c numeric, g numeric, fibra numeric,
      azucar numeric, sodio_mg numeric, grasa_sat numeric,
      micronutrientes jsonb, codigo_barras text unique null,
      verificado bool default false, fuente text, embedding vector(1536));
CREATE INDEX ON foods USING hnsw (embedding vector_cosine_ops)
    WITH (m = 32, ef_construction = 200);
CREATE INDEX ON foods USING gin (nombre_norm gin_trgm_ops);

recipes(id uuid pk, nombre text, descripcion text, imagen_url text,
        kcal int, p int, c int, g int, fibra int, tags text[],
        meal_time enum('desayuno','almuerzo','cena','snack'),
        prep_min int, instrucciones text[], verificada_por text,
        -- Provenance (lets us quarantine a bad LLM batch later, finding #26).
        source_batch text null,
        -- Denormalised allergen list for fast WHERE NOT (allergens && $1) filtering.
        -- Source of truth remains recipe_allergens; trigger keeps this column in sync.
        allergens text[] not null default '{}',
        embedding vector(1536), created_at timestamptz);

recipe_components(id uuid pk,
                  recipe_id uuid not null references recipes(id) on delete cascade,
                  food_id uuid null references foods(id) on delete restrict,
                  sub_recipe_id uuid null references recipes(id) on delete restrict,
                  cantidad_g numeric, modificador text, posicion int);
-- Composition Pattern: recipes compose foods + sub-recipes + modifiers.

-- Closed allergen vocabulary (ADR-0001). Sesame included per FALCPA 2023 (top-9).
-- Declared BEFORE recipe_allergens so the FK column can reference the enum type.
CREATE TYPE allergen_enum AS ENUM (
    'dairy','gluten','tree_nuts','peanuts','shellfish','fish','egg','soy','sesame'
);

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
            SELECT array_agg(allergen::text ORDER BY allergen)
              FROM recipe_allergens
             WHERE recipe_id = affected_recipe
       ), '{}'::text[])
     WHERE id = affected_recipe;

    RETURN NULL;
END;
$$;

CREATE TRIGGER trg_sync_recipe_allergens
    AFTER INSERT OR UPDATE OR DELETE ON recipe_allergens
    FOR EACH ROW EXECUTE FUNCTION sync_recipe_allergens();

-- Defence-in-depth: CHECK constraint pins the denorm column to the closed vocabulary
-- (cast through the enum array so unknown tokens cannot survive a manual UPDATE).
ALTER TABLE recipes
    ADD CONSTRAINT recipes_allergens_closed_vocab
    CHECK (allergens <@ ARRAY[
        'dairy','gluten','tree_nuts','peanuts','shellfish','fish','egg','soy','sesame'
    ]::text[]);

-- HNSW index tuning (finding #20). Recall@10 ≥ 0.95 gated in tests/perf/test_vector_recall.py.
CREATE INDEX ON recipes USING hnsw (embedding vector_cosine_ops)
    WITH (m = 32, ef_construction = 200);
CREATE INDEX ON recipes USING gin (allergens);
```

### Plan
```sql
plans(id uuid pk,
      user_id uuid not null references users(id) on delete cascade,
      tipo enum('dia','semana','mes'),
      total_dias int, dia_actual int,
      estado enum('activo','completado','cancelado'),
      objetivo text, comidas_por_dia int, preferencias text[],
      kcal_objetivo int,
      -- Optimistic-locking version for the state machine (finding #17).
      version int not null default 0,
      created_at timestamptz);
CREATE UNIQUE INDEX one_active_plan ON plans(user_id) WHERE estado='activo';

plan_days(id uuid pk,
          plan_id uuid not null references plans(id) on delete cascade,
          indice_dia int, fecha date, completado bool);
plan_meals(id uuid pk,
           plan_day_id uuid not null references plan_days(id) on delete cascade,
           tiempo enum('desayuno','almuerzo','cena','snack'),
           recipe_id uuid null references recipes(id) on delete restrict,
           kcal int, p int, c int, g int,
           agua_ml int, agua_pct numeric, completada bool,
           swapped_from uuid null);
```

### Tracking
```sql
food_logs(id uuid pk,
          user_id uuid not null references users(id) on delete cascade,
          fecha date,
          tiempo enum('desayuno','almuerzo','cena','snack'),
          food_id uuid null references foods(id) on delete restrict,
          recipe_id uuid null references recipes(id) on delete restrict,
          nombre_libre text null,
          cantidad_g numeric, kcal int, p int, c int, g int,
          metodo enum('foto','voz','texto','codigo','busqueda','manual'),
          confianza numeric(4,3) null, source_image_url text null,
          -- Idempotency-Key support (§8, finding #11). Hash retained 24h, then NULLed by job.
          idempotency_key text null,
          -- Prompt provenance for vision/text-parse paths (finding #13).
          prompt_sha256 text null,
          created_at timestamptz);
CREATE INDEX ON food_logs(user_id, fecha);
CREATE UNIQUE INDEX one_log_per_idem_key
    ON food_logs(user_id, idempotency_key) WHERE idempotency_key IS NOT NULL;

-- Timescale hypertables. FK to users for cascade; hypertable chunks inherit it.
water_logs(time timestamptz,
           user_id uuid not null references users(id) on delete cascade,
           ml int, meta_ml int);
SELECT create_hypertable('water_logs','time');

weight_logs(time timestamptz,
            user_id uuid not null references users(id) on delete cascade,
            peso_kg numeric,
            grasa_pct numeric null, cintura_cm numeric null, foto_url text null);
SELECT create_hypertable('weight_logs','time');

-- Continuous aggregate: biometric_aggregates_daily (14d / 30d rolling means)

fasting_sessions(id uuid pk,
                 user_id uuid not null references users(id) on delete cascade,
                 metodo_h int check(metodo_h in (16,18,20)),
                 inicio_ts timestamptz, fin_ts timestamptz null,
                 duracion_s int null, meta_s int, cumplido bool);

daily_goals(user_id uuid not null references users(id) on delete cascade,
            fecha date,
            item enum('desayuno','almuerzo','cena','agua'),
            completado bool, auto bool, completado_at timestamptz,
            primary key(user_id,fecha,item));

grocery_lists(id uuid pk,
              plan_id uuid not null references plans(id) on delete cascade,
              generada_en timestamptz);
grocery_items(id uuid pk,
              list_id uuid not null references grocery_lists(id) on delete cascade,
              categoria enum('frutas_verduras','proteinas','lacteos','despensa','otros'),
              nombre text, cantidad text, comprado bool);

-- Progress photos (ADR-0005 lists this table in the hard-delete cascade; finding #32).
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
        tipo enum('diaria','ayuno','proteina'),
        valor int, ultimo_dia date, primary key(user_id,tipo));
achievements(user_id uuid not null references users(id) on delete cascade,
             codigo text, desbloqueado_en timestamptz,
             primary key(user_id,codigo));
```

### Coach
```sql
coach_conversations(id uuid pk,
                    user_id uuid not null references users(id) on delete cascade,
                    titulo text, created_at timestamptz);
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
           created_at timestamptz default now());
CREATE UNIQUE INDEX one_active_prompt_per_name
    ON ai_prompts(name) WHERE active = true;

feature_flags(key text primary key, enabled bool not null default false,
              rollout_pct int not null default 0 check(rollout_pct between 0 and 100),
              payload jsonb not null default '{}'::jsonb,
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
```

Auth: Bearer JWT (RS256, 15min) + opaque rotating refresh.
Rate limit (Redis sliding window): 60/min user, 5/min `/ai/*`, 10/min `/auth/*`.
OpenAPI auto + ReDoc at `/docs`.

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
     `{items:[{nombre, cantidad_estimada_g, kcal, p, c, g, confianza}]}`.
   - For each item: trigram + embedding lookup in `foods`. Match if confianza > 0.7.
   - Insert `food_logs(metodo='foto', confianza=…)`.
   - Publish `FoodLogged` event → handlers (daily_goals, streak).
   - Notify client via Redis pubsub `user:{id}` → SSE.

### 9.2 Dynamic metabolic recalibration
Triggered by `WeightLogged`. Formal contract — see ADR-0002 for the rationale.

Inputs (last 14d):
- `weights = [(day_index, peso_kg)]` (require `len(weights) >= 7`, else **skip**).
- `kcal_in[14d]` daily intake series from `food_logs`.
- `tdee_actual` from the current `nutritional_goals` row.

Definitions:
- `slope_kg_per_day = OLS_linear_regression(weights).slope`  (ordinary least squares
  of `peso_kg` against `day_index`).
- `observed_tdee_inferred = mean(kcal_in[14d]) - slope_kg_per_day * 7700`.
- `mifflin_recalc = MifflinStJeor(sexo, peso_kg_actual, talla, edad) * factor_actividad`.
- `tdee_nuevo = round( 0.5 * mifflin_recalc + 0.5 * observed_tdee_inferred )`
  clamped to `tdee_actual ± 15%`.
- `esperado_kg_dia = (mean(kcal_in[14d]) - tdee_actual) / 7700`.
- `delta_ratio = slope_kg_per_day / esperado_kg_dia` (skip if `|esperado_kg_dia| < 1e-4`).

Trigger (all must hold):
1. `|delta_ratio - 1| > 0.5`.
2. `n_days >= 14`.
3. `days_since_last_recalibration >= 14`  (cool-down to prevent oscillation).

On trigger:
- Expire current `nutritional_goals` row (`vigente_hasta = now()`).
- Insert new row with new TDEE, derived macros and water target,
  `motivo='plateau' | 'weight_change'`.
- Publish `GoalsRecalibrated`.

Edge cases (covered by tests, see ADR-0002):
- Athlete bulk: positive slope expected → no trigger if `objetivo='ganar_musculo'`
  and `delta_ratio ∈ [0.7, 1.5]`.
- Post-partum / illness markers: feature-flag `recalibration.enabled` per user can
  pause until cleared.
- Insufficient data (`< 7` weight points in 14d): skip silently, emit
  `recalibration_skipped_total{reason="insufficient_data"}`.

### 9.3 Plan lifecycle (state machine)
```
PATCH /plans/{id}/meals/{mid}/complete
  -> mark completed
  -> if all day's meals complete -> DayCompleted
       if tipo='dia': celebration, flag regenerate tomorrow
       elif dia_actual < total_dias: dia_actual++
       else: estado='completado', CTA newplan
  -> update streak 'diaria'
  -> update daily_goals (desayuno/almuerzo/cena auto)
```

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
   denormalised `recipes.allergens` array (`NOT (recipes.allergens && $alergias)`); filter
   by objective + meal_time + tag preferences; filter contra-indicated conditions.
3. Seeded shuffle + embedding similarity score against profile vector.
4. Per-day macro balancing: `sum(kcal) ∈ kcal_objetivo ± 5%`, `protein >= goal * 0.95`.
5. **Repetition cap** (deterministic, applies to `tipo in ('semana','mes')`):
   - At most **2** occurrences of the same `recipe_id` in **any rolling 7-day window**.
   - For `tipo='mes'`: additionally at most **4** occurrences of the same recipe in the
     full 30-day plan (prevents the same dish appearing every Monday).
   - For `tipo='dia'`: rule does not apply.
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

- Hierarchy: `DomainError` → `ValidationError`, `NotFoundError`, `ConflictError`, `BusinessRuleViolation`.
- Global FastAPI handler → RFC 7807 `application/problem+json`.
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

- `tests/unit/domain` — VOs, Mifflin formulas, recipe composition, macro balance.
- `tests/unit/application` — use cases with in-memory repos.
- `tests/integration` — pytest + testcontainers (real Timescale, Redis).
- `tests/contract` — schemathesis over OpenAPI.
- `tests/e2e` — onboarding → plan → logs → recalibration.
- factory-boy fixtures.
- mutmut mutation tests over `nutrition/domain`.
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

## 21. Vocabulary & i18n contract

- **System identifiers** (enums, column names, JSON keys in DB rows): **Spanish**
  snake_case as already defined in §7. Rationale: domain language of the product
  is Spanish; localisation effort is towards en-US, not away from it. (Reverses the
  earlier note in `nova-clinical-nutrition-generator.md`; the generator agent is to
  be updated separately.)
- **External catalog inputs** (`nova_meals_catalog.json`): currently English. The
  ingest pipeline §20 translates via a fixed mapping table. The mapping is the
  authoritative bridge — no other code path translates enum values.

Mapping table (excerpt, full table lives in the catalog-ingest spec):

| Catalog (en) | DB (es) |
|---|---|
| `breakfast` | `desayuno` |
| `lunch`     | `almuerzo` |
| `dinner`    | `cena` |
| `snack`     | `snack` |
| `weight_loss` | `bajar` |
| `weight_maintenance` | `mantener` |
| `muscle_building` / `build_muscle` / `muscle_hypertrophy` | `ganar_musculo` |
| `weight_gain` | `ganar_peso` |
| `general_health` / `general_wellness` | `salud` |

User-facing strings (recipe names, descriptions) are stored as-is and localised at
the presentation layer.

## 22. Snack catalog gap (blocker)

The current `data/meals/nova_meals_catalog.json` contains **0** records with
`mealtime='snack'` (audit: `{breakfast: 600, lunch: 800, dinner: 600, snack: 0}`).
The spec mandates `snack` in `meal_time` enum and `comidas_por_dia` can include
snack slots. Plans generated today with snack slots would be empty or crash.

Two mutually exclusive resolutions; **(a) is the chosen path**:

(a) **Generate ≥100 snack recipes** via `nova-clinical-nutrition-generator` before
    plan generation goes live. Recommended target: 200 (≈10% of corpus). Distribution:
    sweet, savoury, high-protein, low-kcal, kid-friendly buckets.

(b) Drop `snack` from `meal_time` enum and clamp `comidas_por_dia` to `[3]` for MVP.
    Re-add snacks post-MVP when curation bandwidth exists.

**Dependency**: implementation of `POST /plans` is blocked on resolution. Tracked by
`tests/data/test_catalog_coverage.py::test_every_meal_time_has_minimum_records`
(min 100 per enum value).
