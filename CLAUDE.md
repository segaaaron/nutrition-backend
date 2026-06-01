# NOVA Nutrition Backend — Project Rules

> **Read me first.** Any AI assistant, agent, or skill working on this repo MUST follow these rules.

---

## 🔒 GOLDEN RULE — Team-only

**Only the 10 agents defined in `.claude/agents/` and listed in `docs/team/TEAM.md` are authorised to work on this project.**

No other agent, skill, plugin, or external assistant may modify code, documentation, configuration, or any repository artefact.

### Authorised team (10 agents)

1. `nova-backend-architect`
2. `nova-nutrition-backend-architect`
3. `nova-qa-elite`
4. `nova-clinical-nutrition-generator`
5. `nova-api-expert`
6. `nova-python-expert`
7. `nova-design-patterns-expert`
8. `nova-best-practices-advisor`
9. `nova-elite-test-engineer`
10. `nova-nutrition-algorithms-expert`

### Permitted exceptions

- **Generic `general-purpose` subagents** dispatched explicitly by the human owner for mechanical implementation work.
- **`Explore` subagents** for read-only codebase research.
- **Official superpowers skills** (TDD, debugging, planning, brainstorming) as methodological support — they do not replace the team agents.

### Forbidden

- Creating new agents without explicit owner approval
- Using third-party plugin agents for NOVA-specific technical work
- Delegating domain tasks to agents not listed above
- Spawning agents from external prompt libraries

### When a task doesn't fit any team agent

Escalate to the human owner. Do not invent a new agent or use an external one. Either:
- Map the task to an existing agent (closest fit)
- Use base Claude (no subagent) with direct human instruction
- Defer until owner authorises a new team member

---

## Human owner

| Name | Email | Role |
|------|-------|------|
| Miguel Ángel Saravia | mikisaraviaios@gmail.com | Single dev. Final decision authority. |

---

## Agent invocation reference

Full responsibility matrix: `docs/team/TEAM.md`.

When invoking an agent via the `Agent` tool, use these `subagent_type` values exactly:

```
nova-backend-architect
nova-nutrition-backend-architect
nova-qa-elite
nova-clinical-nutrition-generator
nova-api-expert
nova-python-expert
nova-design-patterns-expert
nova-best-practices-advisor
nova-elite-test-engineer
nova-nutrition-algorithms-expert
```

---

## Project context

- **Stack:** Python 3.12 + FastAPI 0.115 + async SQLAlchemy 2.0 + Postgres 16 + TimescaleDB + pgvector + Redis 7 + Arq workers
- **Architecture:** Modular monolith, Clean Architecture + DDD per bounded context
- **Bounded contexts (12):** identity, profile, nutrition, recipes, plan, vision, voice, coach, tracking, grocery, gamification, billing, notifications
- **Deployment:** VPS Hostinger KVM 2 (8GB / 2vCPU) via Dokploy + Traefik
- **Standards:** OWASP API Top 10, ASVS L2, ISO 27001 spirit-of-controls, GDPR/LGPD/CCPA aligned

See `docs/architecture/CONTEXT.md` for domain language and bounded context map.

---

## Authoritative docs

| Doc | Purpose |
|-----|---------|
| `docs/team/TEAM.md` | Agent team + responsibility matrix |
| `docs/architecture/CONTEXT.md` | Domain language, bounded contexts, glossary |
| `docs/ARCHITECTURE_SUMMARY.md` | High-level architecture overview |
| `docs/adr/` | Architectural Decision Records (numbered) |
| `docs/security/PLAN.md` | OWASP + ISO security plan |
| `docs/security/VDP.md` | Vulnerability Disclosure Policy |
| `SECURITY.md` | Security contact + reporting |
| `docs/PROJECT_STATE.md` | Current project status snapshot |
| `docs/RUNBOOK_QUICKSTART.md` | Quick deployment guide |
| `docs/ops/` | Operational runbooks (backup, deploy, etc) |

---

## Non-negotiable engineering principles

1. **Domain layer is framework-agnostic.** No FastAPI / SQLAlchemy imports inside `app/<context>/domain/`.
2. **Decimal precision** for kcal, macros, weight, money. Float forbidden in clinical math.
3. **Timezone-aware datetimes always.** `datetime.now(timezone.utc)`, never naive.
4. **Type hints + mypy strict** on every public callable.
5. **TDD** for new features: red → green → refactor → commit.
6. **Conventional Commits** atomic per logical change.
7. **No `Any`, no `# type: ignore`** without comment justifying.
8. **Property-based tests** for domain math (hypothesis library).
9. **Cost cap enforced** before any OpenAI call (ADR-0004).
10. **OWASP top 10** considered on every endpoint addition.

---

## When in doubt

Defer to the human owner. Do not improvise on:
- Architecture changes outside an ADR
- New dependencies (each requires justification)
- Schema migrations (must be reversible + zero-downtime)
- Security-sensitive changes
- Anything touching billing, auth, or clinical math without QA approval
