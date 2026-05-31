# Conversation Decision History

Chronological log of every load-bearing decision the product owner (Miguel) made during PO ↔ architect ↔ QA exchanges. Each entry: what was on the table, what was chosen, why.

## Session 1 (2026-05-30 → 2026-05-31)

### Decision 1 — Stack runtime
- **Asked:** Node.js + TypeScript / Python + FastAPI / Go
- **Chosen:** **Python 3.12 + FastAPI**
- **Rationale:** native fit for AI/ML pipelines (vision, embeddings, STT, planner), Pydantic v2 ergonomics for clinical schemas, async-first with `asyncpg`.

### Decision 2 — Scope MVP
- **Asked:** minimum / standard / full (MVP + AI)
- **Chosen:** **Full (MVP + AI)**
- **Rationale:** competitive moat depends on coach + vision shipping on day 1; "AI later" would let competitors hold the position.

### Decision 3 — Deploy strategy
- **Asked:** Docker Compose / managed AWS / managed GCP
- **Chosen:** **Docker Compose, cloud-agnostic, orchestrated by Dokploy**
- **Rationale:** zero lock-in, portable to any KVM, free orchestrator, friendly for solo founder.

### Decision 4 — VPS provider (initial exploration)
- **Bluehost:** rejected (shared hosting, not KVM, oversold CPU, no Docker-friendly).
- **Hostinger KVM 2 (current, ID 1544011, 8GB / 100GB NVMe / 2 vCPU):** evaluated — sufficient for MVP up to ~1,500 active users.
- **Contabo:** recommended price/perf but oversold CPU concerns and weaker network.
- **Hetzner CX42 (€13/mo, 8 vCPU / 16 GB / 160 GB):** premium option for when load grows.
- **Chosen:** **stay with Hostinger 8GB now**; migrate to Hetzner when active users > 1,500.

### Decision 5 — Auth strategy
- **Chosen:** **own JWT (HS256, rotating refresh) + OAuth (Google, Apple) + OTP (email)**.
- **Rationale:** keep control of session lifecycle, GDPR erasure, no third-party identity vendor lock-in.

### Decision 6 — Image storage
- **Chosen:** **defer object storage to post-MVP**; store paths locally on VPS during MVP, migrate to Firestore/Cloud Storage later when scale demands.
- **Rationale:** keep cost flat; pyvips already compresses + EXIF-strips at ingest, so per-image footprint is low.

### Decision 7 — Payment providers
- **Chosen:** **Stripe (US/CA/EU/UK) + Mercado Pago (LatAm)** behind a gateway router that picks provider by country.
- **Rationale:** Stripe is canonical for first-world; MP is required for LatAm card+pix+oxxo coverage.

### Decision 8 — Canonical language (REVERSAL)
- **Initial plan:** Spanish (ES) as canonical IDs for foods/recipes/conditions.
- **Reversed to:** **English (EN) as canonical**, with i18n table for ES, PT, FR, DE translations.
- **Rationale:** industry best practice; data interop with USDA / OpenFoodFacts / FDC; cleaner JSON keys; ADR-0007.

### Decision 9 — Multi-region from day 1
- **Chosen:** **multi-region at launch** (US, CA, EU, UK, LatAm) — not "US first, expand later".
- **Rationale:** LatAm-first moat only matters if catalog ships with LatAm regions live; ADR-0008 governs per-region food availability flags.

### Decision 10 — AI models locked
- **Vision:** `gpt-4o` (confidence threshold ADR-0003).
- **Coach chat + Plan L4 coherence:** `gpt-4o-mini`.
- **STT:** `whisper-1`.
- **Embeddings:** `text-embedding-3-large` (HNSW index m=32, ef=200).
- **Rationale:** ADR-0006 model selection matrix balances accuracy and cost. No gpt-4o escalation in coach path — mini only.

### Decision 11 — Image compression
- **Chosen:** **yes, pyvips already in spec** — compress + EXIF strip on ingest.
- **Rationale:** RAM-light, fast, keeps VPS storage flat.

### Decision 12 — Coach architecture (4-camino)
- **Chosen distribution:**
  - Templates 40% (deterministic, $0)
  - Cache 20% (Redis hit, $0)
  - gpt-4o-mini 35% (~$0.0003/turn)
  - Refuse path 5% (medical / out-of-scope)
- **No gpt-4o escalation.** Mini handles all generative turns.
- **Rationale:** keeps coach cost predictable; refuse path prevents hallucinated medical advice (grounded in `docs/qa/coach_golden_set.md` — 20 medical_refuse golden cases).

### Decision 13 — Plan generation 4-layer pipeline
- **L1:** SQL deterministic eligibility filter (allergens hard-exclude, condition gates, region availability).
- **L2:** macro-balanced shortlist with per-day repetition cap.
- **L3:** hybrid ranking (taste-EMA + cultural + prep + novelty + adherence).
- **L4:** LLM coherence pass (`gpt-4o-mini`) with Redis 24h cache.
- **Rationale:** deterministic-first keeps cost flat and the LLM only resolves narrative coherence over a pre-validated set.

### Decision 14 — Sprint order locked (8 sprints)
- 0: spec + ADRs + agents
- 1: scaffolding + audit + seed
- 2: identity + profile + nutrition + recipes + plan
- 3: tracking + observability
- 4: vision + voice + coach
- 5: notifications + gamification handlers + worker
- 6: tracking expansion + grocery + gamification full
- 7: billing + i18n + load tests
- 8: ops runbooks + final docs + pre-launch QA review

### Decision 15 — Local-first testing before Dokploy
- **Chosen:** stand stack up locally with `docker compose`, smoke-test, then provision Dokploy on Hostinger.
- **Rationale:** isolate "does the code work" from "does the deploy pipeline work".

### Decision 16 — Clinical vocabulary
- **Chosen:** **14-allergen superset** (US + EU + LatAm) and **25 canonical conditions** (ADR-0001).
- **Rationale:** one schema covers all target regions; per-region label compliance handled in presentation layer.

### Decision 17 — Metabolic recalibration (ADR-0002)
- **Chosen:** TDEE retunes from real weight delta vs predicted, applied weekly.
- **Rationale:** Mifflin estimate alone drifts; the moat is *adaptive* plans, not static ones.

### Decision 18 — Cost cap (ADR-0004)
- **Chosen:** hard cap **$1.50 / user / day** on OpenAI spend; soft warn at $0.50.
- **Rationale:** worst-case abuser does not blow unit economics.

### Decision 19 — GDPR / LGPD erasure (ADR-0005)
- **Chosen:** 30-day grace period after delete request, then hard cascade across all aggregates.
- **Rationale:** balance regulator requirement with accidental-delete recovery.

### Decision 20 — Vector store
- **Initial discussion:** Qdrant / Pinecone / pgvector.
- **Chosen:** **pgvector** (HNSW m=32 ef=200) — purge Qdrant from architects (`4db4ad6`, `820dd11`).
- **Rationale:** one engine, no extra container, RAM budget on 8GB VPS does not afford Qdrant.

### Decision 21 — Cleanup pipeline for seed catalog
- **Chosen:** `audit_catalog.py` with 8 gates + lexicon + `--apply-fixes`; run on seed, commit `reports/cleaned.json`.
- **Outcome:** 2 duplicate cases need manual resolution before snack generation.

### Decision 22 — Composition Pattern for recipes
- **Chosen:** recipe = template + ingredient list resolved at query time (not hard-coded rows per locale).
- **Rationale:** enables dynamic scaling, allergen swap, region availability, all without table explosion.

### Decision 23 — Bottleneck prevention budget
- **Chosen:** 10 principles enforced — cursor pagination, idempotency-key, circuit breakers on external APIs, Redis rate-limit sliding window, cost cap, continuous aggregates Timescale, GIN array index allergens/regions, partial unique indexes (one_active_plan, one_current_goals), triggers for denorm sync, HNSW vector index.
- **Rationale:** every hot path bounded so 8GB / 2vCPU does not become a bottleneck.

### Decision 24 — FCM iOS deferred
- **Chosen:** Android FCM + web push (VAPID) on day 1; iOS deferred until App Store presence exists.
- **Rationale:** iOS APNs cert requires App Store record.

### Decision 25 — Anti-cheat leaderboard gated
- **Chosen:** leaderboard ships behind feature flag; opens once abuse model is in place.
- **Rationale:** unguarded leaderboards get gamed instantly; not worth shipping broken.

### Decision 26 — Observability MVP
- **Chosen:** `/healthz` + `/readyz` + Prometheus counters; Sentry + Grafana Cloud optional opt-in.
- **Rationale:** zero-cost baseline; paid telemetry only if a real incident demands it.

### Decision 27 — Worker (Arq vs Celery)
- **Chosen:** **Arq**.
- **Rationale:** async-native (matches FastAPI runtime), Redis-only (no separate broker), lighter RAM footprint than Celery.

### Decision 28 — Coach SSE streaming
- **Chosen:** SSE over WebSocket for coach response stream; Redis pub/sub backplane.
- **Rationale:** unidirectional fits the use case; SSE survives proxies that drop WS; trivial reconnect.

### Decision 29 — i18n strategy (ADR-0007)
- **Chosen:** EN canonical IDs; `i18n_translations` table keyed by `(canonical_id, locale)`; seed script for 5 locales.
- **Rationale:** decouples display from logic; no schema churn when adding a locale.

### Decision 30 — Multi-region catalog (ADR-0008)
- **Chosen:** per-food / per-recipe `regions` GIN-indexed array; filter at L1 eligibility.
- **Rationale:** one catalog, region-aware availability, no per-region forks.

### Decision 31 — Pre-launch QA gate
- **Chosen:** require `docs/qa/2026-06-pre-launch-review.md` go/no-go checklist green before first Dokploy deploy.
- **Outcome:** all blockers either resolved or tracked in Pending Manual Actions.

### Decision 32 — Commit hygiene
- **Chosen:** never `--no-verify`; conventional commits; one bounded context per commit where possible.
- **Rationale:** clean history for future bisects.
