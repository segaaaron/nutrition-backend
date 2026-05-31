# NOVA Backend Architecture Summary

## Philosophy

Clean Architecture + Domain-Driven Design per bounded context. Modular monolith — **not** microservices — because the entire system fits on a single 8GB / 2vCPU VPS for MVP and splitting prematurely would 5x ops cost for zero throughput gain. The domain layer is framework-agnostic (no FastAPI / SQLAlchemy imports inside `domain/`). The rest is async end-to-end: FastAPI + asyncpg + Redis + Arq.

## Layered Structure per Bounded Context

```
app/<context>/
├── domain/          (entities, VOs, aggregates, domain events, repository interfaces)
├── application/     (use cases, command/query handlers, orchestrators)
├── infrastructure/  (SQLAlchemy repos, OpenAI clients, Redis adapters, external API gateways)
└── presentation/    (FastAPI routers, request/response Pydantic models, SSE handlers)
```

Dependency direction: presentation → application → domain ← infrastructure. Infrastructure depends on domain (implements its repository interfaces) but domain never imports infrastructure.

## Bounded Contexts (12)

| Context | Responsibility | Key aggregates |
|---|---|---|
| **identity** | auth (JWT + OAuth Google/Apple + OTP email) + GDPR/LGPD erasure with 30-day grace | `User`, `Session`, `EraseRequest` |
| **profile** | user profile, locale + region derivation, allergens, conditions | `UserProfile`, `Allergens`, `Conditions` |
| **nutrition** | Mifflin BMR + TDEE + macro split + adaptive recalibration (ADR-0002) | `EnergyGoals`, `MacroTargets`, `RecalibrationRun` |
| **recipes** | canonical catalog (EN), hybrid search (trigram + pgvector), i18n | `Recipe`, `Ingredient`, `RecipeTranslation` |
| **plan** | 4-layer pipeline (L1 SQL eligibility → L2 macro shortlist → L3 hybrid ranking → L4 LLM coherence) | `Plan`, `PlanDay`, `PlanItem` |
| **vision** | photo upload → pyvips compress → gpt-4o vision → parser | `VisionJob`, `FoodCandidate` |
| **voice** | whisper STT + NLP food parser + text quick-log | `VoiceJob`, `TranscribedLog` |
| **coach** | 4-camino router (templates/cache/mini/refuse) + SSE streaming | `Conversation`, `Turn`, `Intent` |
| **tracking** | food_log query, water, weight (Timescale), fasting, progress photos | `FoodLog`, `WaterLog`, `WeightLog`, `FastingSession`, `ProgressPhoto` |
| **grocery** | generate / scale / share / categorize lists | `GroceryList`, `GroceryItem` |
| **gamification** | achievements, streaks, levels, leaderboard (flag-gated) | `Achievement`, `Streak`, `LevelProgress`, `Leaderboard` |
| **billing** | Stripe + Mercado Pago + gateway router by country | `Subscription`, `Invoice`, `WebhookEvent` |

## Cross-Cutting Concerns

- **`core/`** — config (pydantic-settings), structured logging, error mapping, DB engine, Redis client, in-process event bus, dependency injection, security (JWT issue/verify), circuit breaker (for OpenAI / Stripe / MP), cost cap (per user/org per day), metrics (Prometheus counters).
- **`shared/`** — value objects shared across contexts (Money, Locale, Region, Mass, Energy, MacroSplit) + unit conversions.
- **`imaging/`** — pyvips compressor + EXIF stripper.
- **`notifications/`** — Web Push (VAPID) dispatcher + FCM scaffold + send orchestrator.

## Data Layer

- **Postgres 16** with extensions:
  - **TimescaleDB-HA** — hypertables for `weight_logs`, `food_logs`, with continuous aggregates for daily rollups (avoids hot-path recomputation).
  - **pgvector** — embeddings for recipes and FAQ; HNSW index (m=32, ef=200).
- **Redis 7** — cache (L4 plan 24h, coach cache 20% path), Arq broker, rate-limit sliding window, SSE pub/sub backplane.

## External Integrations

- **OpenAI** — gpt-4o (vision), gpt-4o-mini (chat + plan L4), whisper-1 (STT), text-embedding-3-large (embeddings).
- **Stripe** — US / CA / EU / UK payments.
- **Mercado Pago** — LatAm (card, pix, oxxo).
- **Cloudflare** — CDN + DDoS (frontend layer).
- **Sentry** — optional, opt-in.
- **Grafana Cloud** — optional, opt-in.

## Key Patterns

- **Composition Pattern** for recipes — recipe = template + resolved ingredients (not hard-coded rows per locale / per region).
- **Repository per aggregate** — one repo interface per aggregate root in `domain/`; SQLAlchemy implementation in `infrastructure/`.
- **In-process domain events** — small event bus in `core/`; handlers subscribe at app boot (e.g. `nutrition` subscribes to `tracking.WeightLogged` for recalibration trigger).
- **Idempotency-Key** on every POST that creates state (plans, logs, payments).
- **Circuit breaker** on every external API client (OpenAI, Stripe, MP).
- **Cursor pagination** on all list endpoints (no offset/limit hot paths).
- **Cost cap per user / org / day** enforced before any OpenAI call (ADR-0004, hard $1.50/user/day).
- **Rate limit** via Redis sliding window per endpoint class.
- **HNSW vector index** (m=32, ef=200) for recipe semantic search.
- **GIN array index** for `allergens[]` and `regions[]` columns.
- **Partial unique indexes** — `one_active_plan_per_user`, `one_current_goals_per_user`.
- **Continuous aggregates** (Timescale) — weight daily rollup, food_log daily rollup.
- **Triggers** for denorm sync — recipe aggregate macros recomputed when ingredients change; allergen array recomputed when an ingredient is tagged.

## 4-Layer Plan Generation Pipeline

| Layer | Mechanism | Cost | Output |
|---|---|---|---|
| **L1 Eligibility** | Pure SQL — hard-exclude allergens, condition gates, region availability filter | $0 | candidate set, often a few hundred recipes |
| **L2 Macro shortlist** | Python — macro-balanced subset with per-day repetition cap | $0 | shortlist of ~30-50 |
| **L3 Hybrid ranking** | Python — weighted score (taste-EMA + cultural fit + prep time + novelty + adherence history) | $0 | ranked top N per slot |
| **L4 LLM coherence** | gpt-4o-mini — narrative coherence, day flow, swap suggestions; **Redis 24h cache by (user, day, shortlist hash)** | ~$0.001 / plan generation | final plan |

## 4-Camino Coach Architecture

| Path | Share | Cost | Trigger |
|---|---|---|---|
| **Templates** | 40% | $0 | deterministic intents (greeting, help, common Qs) |
| **Cache hit** | 20% | $0 | Redis lookup on `(intent, normalized_input)` |
| **gpt-4o-mini** | 35% | ~$0.0003 / turn | generative coach reply |
| **Refuse** | 5% | $0 | medical / out-of-scope (golden set in `docs/qa/coach_golden_set.md`) |

**No gpt-4o escalation in coach path.** Mini-only by design; this keeps coach unit economics predictable and prevents medical-advice hallucination via the deterministic refuse path.

## Bottleneck Prevention (10 principles)

1. Cursor pagination on every list endpoint.
2. Idempotency-Key on every state-creating POST.
3. Circuit breakers on all external APIs.
4. Redis sliding-window rate limit per endpoint class.
5. Cost cap per user/org/day before any LLM call.
6. Continuous aggregates in Timescale for hot dashboards.
7. GIN array index for allergens + regions.
8. Partial unique indexes for one-active-X invariants.
9. Triggers for denormalised aggregate sync (recipe macros, allergen rollup).
10. HNSW vector index sized for the catalog (m=32, ef=200).

## Resource Budget — Hostinger KVM 2 (8GB / 2vCPU)

| Container | RAM target | Notes |
|---|---|---|
| postgres (Timescale-HA + pgvector) | ~2.5 GB | shared_buffers ~1GB, work_mem 16MB |
| redis | ~256 MB | maxmemory policy allkeys-lru |
| api (FastAPI + uvicorn, 2 workers) | ~700 MB | gunicorn-uvicorn worker class |
| worker (Arq) | ~300 MB | 1 process, 4 concurrent jobs |
| nginx / dokploy proxy | ~100 MB | |
| OS + headroom | ~4 GB | leaves margin for spikes |

Hard upgrade trigger: active users > 1,500 → migrate to Hetzner CX42 (€13/mo, 8 vCPU / 16 GB / 160 GB NVMe).
