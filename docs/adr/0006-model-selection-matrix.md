# ADR-0006 — OpenAI model selection matrix

Status: accepted (2026-05-30)
Supersedes: none.
Related: ADR-0003 (vision confidence), ADR-0004 (cost cap).

## Context

NOVA backend talks to OpenAI in five distinct hot paths (vision, STT, chat
coach, intent classifier, embeddings). Picking a different model per path
is a fixed cost win (~5×) over a "one model fits all" policy, but it also
lets us flip individual paths to a backup provider (Anthropic, Mistral)
without rewriting the bounded context.

## Decision

| Path                | Model                     | Why                                        | Cost / 1M in (USD) |
|---------------------|---------------------------|--------------------------------------------|--------------------|
| Vision IA           | `gpt-4o-2024-08-06`       | strict JSON + image; only frontier model worth the spend | 2.75 in / 11.00 out |
| Coach chat (mini)   | `gpt-4o-mini`             | streaming + JSON; 16× cheaper, good enough for grounded RAG | 0.17 in / 0.66 out |
| Intent classifier   | `gpt-4o-mini`             | single short call, strict enum             | 0.17 in / 0.66 out |
| Plan L4 coherence   | `gpt-4o-mini`             | one call/plan, 24h Redis cache (ADR-0004)  | 0.17 in / 0.66 out |
| STT (voice log)     | `whisper-1`               | only practical hosted ASR at this price    | 0.006 / minute     |
| Embeddings (search) | `text-embedding-3-large`  | 1536-dim truncated, fits HNSW idx          | 0.143              |

Model names are frozen in `app/core/config.py` and referenced from infrastructure adapters only — domain code is model-agnostic.

## Downgrade path (incident playbook)

| Trigger                                | Action                                     |
|----------------------------------------|--------------------------------------------|
| OpenAI vision outage / kill switch     | Disable `POST /logs/food/photo` (return 503), keep text+voice+manual |
| Coach mini outage                      | Fall through to Camino 1 templates only (40% traffic served, 60% refused gracefully) |
| Embedding outage                       | Fall back to trigram-only food match (already implemented) |
| Whisper outage                         | Disable `POST /logs/food/voice`, keep text+manual |
| Anthropic Claude becomes price-competitive on mini-tier | swap `OpenAICoachClient` to a `ClaudeCoachClient` impl; domain unchanged |

A future swap to `claude-haiku` as the mini backup is the most likely
near-term migration. Keep the `CoachProvider` Protocol stable.

## Quarterly review trigger

The architect re-evaluates this matrix every 90 days, or whenever:
- OpenAI publishes a >25% cheaper model in any tier.
- Per-user p95 daily cost exceeds $0.50 (33% of the $1.50 cap).
- A judge-eval run (Phase 2) shows the mini grounding score drops below 0.80.

## Consequences

- Cost projection per active user / day:
  - 2 vision photos × $0.007 = $0.014
  - 15 coach msgs × $0.0003 = $0.0045 (Caminos 1+2 free, Camino 3 ~35%)
  - 1 macro_repair × $0.0003 = $0.0003
  - 1 weekly_review × $0.0003 (only Sundays) = $0.00004
  - Embeddings on food matches ≈ $0.0001
  - **Total ≈ $0.019 / active user / day** — well under the $1.50 cap.

- Risk: gpt-4o-2024-08-06 deprecation. Mitigated by pinning the snapshot
  and tracking OpenAI's deprecation calendar in the napkin.
