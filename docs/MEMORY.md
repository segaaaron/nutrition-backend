# NOVA Nutrition Backend — Project Memory

## Last Updated
2026-05-31

## Quick Resume for New Session

NOVA (Neural Nutrition AI) is a B2C nutrition app combining an AI coach, computer-vision meal logging, and nutritionally-grounded meal planning. The backend MVP is **complete in code** (8 sprints, ~40 commits, ~18.8k LoC of Python across 12 bounded contexts) and now sits at the *local-test → Dokploy deploy* boundary. All architectural decisions are locked: Python 3.12 + FastAPI, Postgres 16 (Timescale + pgvector), Redis 7, Arq worker, OpenAI (gpt-4o vision + gpt-4o-mini chat/plan + whisper + text-embedding-3-large), Stripe + Mercado Pago for billing, EN as canonical language with i18n for ES/PT/FR/DE, multi-region day 1 (US, CA, EU, UK, LatAm).

The next concrete moves are: (1) bring the Docker stack up locally, run migrations + seeds, smoke-test endpoints; (2) generate the snack catalog (~$3 OpenAI spend); (3) provision Dokploy on the existing Hostinger KVM 2 VPS (ID 1544011, 8GB RAM, 100GB NVMe, 2 vCPU) and deploy; (4) kick off the mobile app. Two seed-catalog duplicates need manual resolution before snack generation. The user wants no premature VPS upgrades — the agreed signal to migrate to Hetzner CX42 (€13/mo) is when active users exceed ~1,500.

## Project Identity

- **Name:** NOVA — Neural Nutrition AI
- **Type:** B2C nutrition app — AI coach + vision IA + adaptive plans
- **Market:** USA + Canada + EU + UK + LatAm (multi-region day 1)
- **Target users:** weight-loss, muscle-gain, general-health audiences
- **Pricing model:** Freemium ($0) + Premium ($9.99/mo US/CA/EU/UK, $4.99/mo LatAm) + Family tier
- **Competitive moat:**
  1. LatAm-first verified canonical food + recipe catalog
  2. Adaptive metabolic recalibration (ADR-0002) — TDEE retunes from real weight delta
  3. Grounded AI coach (no hallucinated medical advice — 4-camino router + refuse path)
  4. Dynamic recipes via Composition Pattern (recipe = template + ingredients; not hard-coded rows)
- **Project owner:** Miguel Angel Saravia Belmonte (mikisaraviaios@gmail.com)

## Stack Locked

| Layer | Choice | Reason |
|---|---|---|
| Runtime | Python 3.12 | best AI/ML pipeline ergonomics; mature async |
| Web framework | FastAPI | async-first, OpenAPI baked-in, Pydantic v2 |
| ORM/DB driver | SQLAlchemy 2.x + asyncpg | async + typed |
| Migrations | Alembic | standard, scriptable |
| Database | Postgres 16 + TimescaleDB-HA + pgvector | timeseries (weight/food_log) + embeddings (HNSW m=32 ef=200) in one engine |
| Cache / broker / pubsub | Redis 7 | cache + Arq broker + rate-limit sliding window + SSE pubsub |
| Background worker | Arq | async-native, Redis-backed, light |
| Image processing | pyvips | low-RAM, fast, EXIF strip |
| AI provider | OpenAI | gpt-4o (vision), gpt-4o-mini (chat/plan), whisper-1 (STT), text-embedding-3-large |
| Payments | Stripe + Mercado Pago | Stripe US/CA/EU/UK; MP LatAm; gateway router by country |
| Push | Web Push (VAPID) + FCM (Android first; iOS deferred) | |
| Deploy | Docker Compose via Dokploy | cloud-agnostic; portable to any KVM |
| Observability | /healthz + /readyz + Prometheus counters + (optional Sentry + Grafana Cloud) | |

## Infrastructure

- **VPS:** Hostinger KVM 2, instance ID **1544011**, 8 GB RAM, 100 GB NVMe, 2 vCPU
- **Deploy target:** Dokploy (Docker Compose orchestrator, free, self-hosted)
- **CDN/DDoS:** Cloudflare (frontend; backend behind it)
- **Resource budget (8GB / 2vCPU):** see `docs/ARCHITECTURE_SUMMARY.md` → "Resource Budget"
- **Upgrade signal:** active users > 1,500 → migrate to **Hetzner CX42** (€13/mo, 8 vCPU / 16 GB / 160 GB NVMe). User explicitly rejected Bluehost; evaluated Contabo + Hetzner; committed to staying on Hostinger 8GB until the signal triggers.

## Models AI

| Use case | Model | Approx cost / call | Notes |
|---|---|---|---|
| Vision meal log | `gpt-4o` | ~$0.01 / image | ADR-0006; confidence threshold ADR-0003 |
| Coach chat (mini path) | `gpt-4o-mini` | ~$0.0003 / turn | 4-camino router — see below |
| Plan generation L4 coherence | `gpt-4o-mini` | ~$0.001 / plan | only after L1+L2+L3 deterministic filtering |
| STT voice log | `whisper-1` | ~$0.006 / min | |
| Embeddings (recipes, FAQs) | `text-embedding-3-large` | ~$0.00013 / 1k tok | HNSW (m=32, ef=200) |
| Snack generation (one-shot batch) | `gpt-4o-mini` | ~$3 total | not yet executed |

**Cost cap (ADR-0004):** hard $1.50 / user / day. Projected steady-state $0.022 / user / day.

## Bounded Contexts (12)

1. **identity** — auth (JWT + OAuth + OTP), GDPR/LGPD account erasure (30-day grace, ADR-0005)
2. **profile** — user_profile, locale, region derivation, allergens, conditions
3. **nutrition** — Mifflin BMR + TDEE + macro split + recalibration (ADR-0002)
4. **recipes** — canonical catalog, hybrid search (trigram + pgvector), i18n
5. **plan** — 4-layer pipeline (L1 SQL eligibility, L2 macro shortlist, L3 hybrid ranking, L4 LLM coherence cached 24h)
6. **vision** — photo upload → pyvips compress → gpt-4o pipeline → parser
7. **voice** — whisper STT + NLP food parser + text quick-log
8. **coach** — 4-camino router (templates 40% + cache 20% + mini 35% + refuse 5%) + SSE streaming
9. **tracking** — food_log query API, water, weight (Timescale), fasting sessions, progress photos (EXIF strip + body comp)
10. **grocery** — generate / scale / share / categorize lists
11. **gamification** — achievements catalog, streaks, levels, leaderboard (anti-cheat gated)
12. **billing** — Stripe + Mercado Pago + gateway router by country

Plus cross-cutting modules: `core/`, `shared/`, `imaging/`, `notifications/`.

## Sprints Completed (Sprint 0 → Sprint 8)

| Sprint | Theme | Key commits |
|---|---|---|
| 0 | Spec + ADRs + agents + EN-canonical reversion + multi-region | `1fa15f1`, `0f386d2`, `5d46c04`, `72da540`, `867372d`, `8f4c6ff` |
| 1 | Scaffolding + audit/cleanup + seed scripts + migration 0001 | `d942ad6`, `4bad582`, `55c1f8c`, `b9fca03`, `5aa3304`, `3f1cb4d`, `fc83bec`, `dcd7227` |
| 2 | identity + profile + nutrition + recipes + plan L1-L4 | `ad4e6a7`, `91b0a44`, `fedda3d`, `b15a636`, `d673acc`, `a3ccb70`, `c7e2204`, `cdfec50`, `4136cd3` |
| 3 | tracking + observability + nutrition cross-context fix | `2391db4`, `ed33d18`, `2edf97e`, `cc7f869` |
| 4 | vision + voice + coach 4-camino + proactive coach features | `dcb28ac`, `fb9b14a`, `3d9edb4`, `b1ede9a` |
| 5 | notifications (web push + FCM) + gamification handlers + worker tasks | `52d6bd2`, `f4f28ea`, `9d318c5`, `42ff932` |
| 6 | tracking expansion (fasting, food_log query, progress photos) + grocery + gamification full | `2d4639e`, `b71e958`, `548ca46`, `52ed804`, `930ff89` |
| 7 | billing + i18n seeds + load tests + migrations 0004-0006 | `04710b1`, `6bae63d`, `d997c63`, `ff0b8b8` |
| 8 | ops runbooks + final spec/README/CONTEXT + pre-launch QA review | `1b09957`, `b3341c5`, `b20f10e` |

**Total commits:** 60. **LoC Python:** ~18,810.

## Files of Interest

- **Spec / context:** `docs/architecture/CONTEXT.md`, `README.md`
- **ADRs:** `docs/adr/0001`..`0008`
- **QA reviews:** `docs/qa/2026-05-30-pre-implementation-review.md`, `docs/qa/2026-05-30-post-fixes-review.md`, `docs/qa/2026-06-pre-launch-review.md`, `docs/qa/coach_golden_set.md`
- **Product strategy:** `docs/product/2026-05-30-meal-planning-strategy.md`
- **Ops runbooks:** `docs/ops/runbook-backup-recovery.md`, `docs/ops/runbook-deploy-hostinger-dokploy.md`
- **Migrations:** `migrations/versions/0001_init.py` … `0006_billing.py`
- **Seed / utility scripts:** `scripts/seed_foods.py`, `scripts/seed_recipes.py`, `scripts/seed_i18n.py`, `scripts/compute_embeddings.py`, `scripts/generate_snacks.py`, `scripts/audit_catalog.py`, `scripts/resolve_ingredients.py`, `scripts/backup.sh`, `scripts/restore.sh`
- **Agents:** `.claude/agents/nova-backend-architect.md`, `nova-nutrition-backend-architect.md`, `nova-clinical-nutrition-generator.md`, `nova-qa-elite.md`
- **Compose / Docker:** `docker-compose.yml`, `docker/`
- **Tests:** `tests/` (nutrition, compliance, contract, e2e, i18n, integration, load, perf, security, unit)
- **Reports:** `reports/` (audit output, cleaned catalog, etc.)

## Pending Manual Actions

1. **Local stack bring-up** — `docker compose up -d`, then `alembic upgrade head`, then seeds.
2. **Resolve 2 catalog duplicates** flagged by `audit_catalog.py` before running `generate_snacks.py`.
3. **Generate snacks** — `python scripts/generate_snacks.py` (~$3 OpenAI).
4. **Provision Dokploy** on Hostinger KVM 2 (1544011) — see `docs/ops/runbook-deploy-hostinger-dokploy.md`.
5. **First deploy** via Dokploy.
6. **Mobile app kickoff** (separate repo).
7. **FCM iOS** — deferred until App Store presence.
8. **MercadoPago webhook HMAC** strict validation — currently lenient.
9. **Anti-cheat leaderboard** — gated behind feature flag; enable post-launch once abuse model exists.

## Cost Projections

| Item | Cost |
|---|---|
| OpenAI per user / day | **$0.022** (steady state) |
| OpenAI hard cap per user / day | **$1.50** (ADR-0004) |
| Ops MVP (Hostinger 8GB + Cloudflare + domain) | **~$30 / mo** |
| Snack generation (one-shot) | ~$3 |
| Upgrade trigger | active users > 1,500 → Hetzner CX42 €13/mo |

## Open Decisions

- None blocking. All Sprint-0 → Sprint-8 decisions resolved. Future deferred items (FCM iOS, anti-cheat leaderboard activation, MP HMAC hardening) are tracked in **Pending Manual Actions** above and in `docs/qa/2026-06-pre-launch-review.md`.
