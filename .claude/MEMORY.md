# Claude Session Memory · NOVA Backend

When starting a new session on this repo, **READ FIRST** (in order):

1. `docs/MEMORY.md` — project state + locked decisions
2. `docs/CONVERSATION_HISTORY.md` — all decisions chronological
3. `docs/PROJECT_STATE.md` — current snapshot
4. `docs/ARCHITECTURE_SUMMARY.md` — technical overview
5. `docs/RUNBOOK_QUICKSTART.md` — how to run / test
6. `docs/CHANGELOG.md` — what shipped each sprint

## User Communication Preferences

- **Mode:** CAVEMAN (full) — terse, fragments OK, drop articles/filler
- **Language:** Spanish (es-PE) for conversation
- **Code, commits, security artifacts:** full English, professional
- Wants **honest opinion**, not platitudes
- Likes **options with trade-offs**, decides quickly when given clear data
- Hates being asked too many questions — prefer execute + flag risks
- Confirms decisions explicitly; once locked, they are locked

## Active Agents (`.claude/agents/`)

- `nova-backend-architect` — general backend architecture
- `nova-nutrition-backend-architect` — DDD + clinical nutrition focus
- `nova-clinical-nutrition-generator` — recipe generation, EN canonical output
- `nova-qa-elite` — QA gate, golden set evaluation

## Tech Stack Locked

| Layer | Choice |
|---|---|
| Runtime | Python 3.12 + FastAPI |
| ORM | SQLAlchemy 2.x + asyncpg + Alembic |
| Database | Postgres 16 + TimescaleDB-HA + pgvector |
| Cache / broker | Redis 7 |
| Worker | Arq |
| Imaging | pyvips |
| AI | OpenAI — gpt-4o (vision), gpt-4o-mini (chat/plan), whisper-1, text-embedding-3-large |
| Payments | Stripe (US/CA/EU/UK) + Mercado Pago (LatAm) |
| Deploy | Docker Compose via Dokploy |
| VPS | Hostinger KVM 2 (ID 1544011, 8GB / 100GB NVMe / 2 vCPU) |

## DO NOT

- Use Spanish canonical IDs (EN canonical is locked — ADR-0007)
- Ask too many questions — user prefers execute + flag
- Suggest premium VPS prematurely (user committed to Hostinger 8GB until > 1,500 active users)
- Add features beyond MVP scope (8 sprints shipped; new scope = new sprint)
- Use `--no-verify` on commits
- Re-introduce Qdrant / Pinecone (pgvector is locked)
- Escalate coach to gpt-4o (mini-only by design)
- Skip the cost cap check before any LLM call
- Touch the leaderboard without the anti-cheat flag

## ALWAYS

- Quote VPS instance ID **1544011** when discussing infra
- Reference ADR numbers when invoking a locked decision
- Prefer one bounded context per commit
- Run tests + smoke before claiming "done"
- Cap each OpenAI call with circuit breaker + cost cap
- Flag duplicates in catalog before any generator run
