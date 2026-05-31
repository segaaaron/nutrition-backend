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
- `MacroBreakdown(p, c, g)` — must satisfy `kcal == p*4 + c*4 + g*9 ± 5%`
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
      email_verified bool, created_at timestamptz, last_login_at timestamptz);
refresh_tokens(id uuid pk, user_id uuid fk, token_hash text,
               expires_at timestamptz, revoked_at timestamptz);
otp_codes(user_id uuid, code_hash text,
          purpose enum('register','reset','login'),
          expires_at timestamptz, attempts int);
```

### Profile
```sql
user_profiles(user_id uuid pk fk, nombre text, edad int check(12<=edad<=100),
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
nutritional_goals(id uuid pk, user_id uuid fk,
                  kcal_min int, kcal_max int,
                  proteina_g int, carbos_g int, grasas_g int, agua_ml int,
                  bmr int, tdee int, factor_actividad numeric(4,3),
                  motivo enum('onboarding','weight_change','goal_change','plateau','manual'),
                  vigente_desde timestamptz, vigente_hasta timestamptz null,
                  created_at timestamptz);
-- Exactly one row per user with vigente_hasta IS NULL (current); others historical.
```

### Recipes
```sql
foods(id uuid pk, nombre text, nombre_norm text, marca text, pais char(2),
      porcion_g numeric, kcal numeric, p numeric, c numeric, g numeric, fibra numeric,
      azucar numeric, sodio_mg numeric, grasa_sat numeric,
      micronutrientes jsonb, codigo_barras text unique null,
      verificado bool default false, fuente text, embedding vector(1536));
CREATE INDEX ON foods USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ON foods USING gin (nombre_norm gin_trgm_ops);

recipes(id uuid pk, nombre text, descripcion text, imagen_url text,
        kcal int, p int, c int, g int, fibra int, tags text[],
        meal_time enum('desayuno','almuerzo','cena','snack'),
        prep_min int, instrucciones text[], verificada_por text,
        embedding vector(1536), created_at timestamptz);

recipe_components(id uuid pk, recipe_id uuid fk,
                  food_id uuid fk null, sub_recipe_id uuid fk null,
                  cantidad_g numeric, modificador text, posicion int);
-- Composition Pattern: recipes compose foods + sub-recipes + modifiers.

recipe_allergens(recipe_id uuid, allergen text);
```

### Plan
```sql
plans(id uuid pk, user_id uuid fk,
      tipo enum('dia','semana','mes'),
      total_dias int, dia_actual int,
      estado enum('activo','completado','cancelado'),
      objetivo text, comidas_por_dia int, preferencias text[],
      kcal_objetivo int, created_at timestamptz);
CREATE UNIQUE INDEX one_active_plan ON plans(user_id) WHERE estado='activo';

plan_days(id uuid pk, plan_id uuid fk, indice_dia int, fecha date, completado bool);
plan_meals(id uuid pk, plan_day_id uuid fk,
           tiempo enum('desayuno','almuerzo','cena','snack'),
           recipe_id uuid fk, kcal int, p int, c int, g int,
           agua_ml int, agua_pct numeric, completada bool,
           swapped_from uuid null);
```

### Tracking
```sql
food_logs(id uuid pk, user_id uuid fk, fecha date,
          tiempo enum('desayuno','almuerzo','cena','snack'),
          food_id uuid null, recipe_id uuid null, nombre_libre text null,
          cantidad_g numeric, kcal int, p int, c int, g int,
          metodo enum('foto','voz','texto','codigo','busqueda','manual'),
          confianza numeric(4,3) null, source_image_url text null,
          created_at timestamptz);
CREATE INDEX ON food_logs(user_id, fecha);

-- Timescale hypertables
water_logs(time timestamptz, user_id uuid, ml int, meta_ml int);
SELECT create_hypertable('water_logs','time');

weight_logs(time timestamptz, user_id uuid, peso_kg numeric,
            grasa_pct numeric null, cintura_cm numeric null, foto_url text null);
SELECT create_hypertable('weight_logs','time');

-- Continuous aggregate: biometric_aggregates_daily (14d / 30d rolling means)

fasting_sessions(id uuid pk, user_id uuid fk,
                 metodo_h int check(metodo_h in (16,18,20)),
                 inicio_ts timestamptz, fin_ts timestamptz null,
                 duracion_s int null, meta_s int, cumplido bool);

daily_goals(user_id uuid, fecha date,
            item enum('desayuno','almuerzo','cena','agua'),
            completado bool, auto bool, completado_at timestamptz,
            primary key(user_id,fecha,item));

grocery_lists(id uuid pk, plan_id uuid fk, generada_en timestamptz);
grocery_items(id uuid pk, list_id uuid fk,
              categoria enum('frutas_verduras','proteinas','lacteos','despensa','otros'),
              nombre text, cantidad text, comprado bool);
```

### Gamification
```sql
streaks(user_id uuid, tipo enum('diaria','ayuno','proteina'),
        valor int, ultimo_dia date, primary key(user_id,tipo));
achievements(user_id uuid, codigo text, desbloqueado_en timestamptz,
             primary key(user_id,codigo));
```

### Coach
```sql
coach_conversations(id uuid pk, user_id uuid fk, titulo text, created_at timestamptz);
coach_messages(id uuid pk, conv_id uuid fk,
               role enum('user','assistant','system'),
               content text, tokens_in int, tokens_out int, created_at timestamptz);
```

### Audit
```sql
audit_log(id bigserial pk, ts timestamptz default now(),
          user_id uuid null, actor_type enum('user','system','admin'),
          action text, target_type text, target_id text, metadata jsonb);
-- Append-only; row-level revoke of UPDATE/DELETE.
```

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
POST   /coach/chat                # SSE stream
GET    /coach/conversations
GET    /coach/conversations/{id}/messages

# Images (internal)
POST   /images/compress
```

Auth: Bearer JWT (RS256, 15min) + opaque rotating refresh.
Rate limit (Redis sliding window): 60/min user, 5/min `/ai/*`, 10/min `/auth/*`.
OpenAPI auto + ReDoc at `/docs`.

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
Triggered by `WeightLogged`:
1. Fetch last 14d `weight_logs` + `food_logs`.
2. `observado_kg_dia = slope(weight)`.
3. `esperado_kg_dia = (mean(kcal_consumido) - tdee_actual) / 7700`.
4. `delta_ratio = observado / esperado`.
5. If `|delta_ratio - 1| > 0.5` and days >= 14:
   - `tdee_nuevo = blend(mifflin_recalc, energy_balance_inferred)`.
   - Expire current `nutritional_goals` row (`vigente_hasta = now()`).
   - Insert new row with `motivo='plateau' | 'weight_change'`.
6. Publish `GoalsRecalibrated`.

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
1. `POST /plans` enqueues `generate_plan_task`.
2. Select recipes: hard-exclude by allergies, filter by objective + meal_time + tag prefs.
3. Random shuffle + embedding similarity score against profile.
4. Per-day macro balancing: `sum(kcal) ∈ kcal_objetivo ± 5%`, `protein >= goal * 0.95`.
5. Avoid repeating same recipe >2× per week.
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

## 13. Observability

- OpenTelemetry SDK + OTLP exporter (configurable).
- `/healthz` liveness, `/readyz` readiness (checks db + redis).
- Sentry SDK FastAPI integration.
- Prometheus `/metrics`: request latency p50/p95/p99, OpenAI token usage, Arq queue depth.
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
- Decide cost cap policy for OpenAI per-user (token budget per day).
- Localization corpus for `es-MX`, `es-PE`, `pt-BR`, `en-US`.
- Verified-food curation workflow (admin tooling) — likely separate spec.
