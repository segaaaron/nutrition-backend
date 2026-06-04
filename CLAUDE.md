# NOVA Nutrition Backend — Project Rules

> **Read me first.** Any AI assistant, agent, or skill working on this repo MUST follow these rules.

---

## 🚫 GOLDEN RULE #0 — Git is owner-exclusive (since 2026-06-01)

**Owner Miguel is the ONLY entity that touches git in this repo.** No AI assistant, agent, skill, or automated tool may execute git modifying commands. Period.

### FORBIDDEN — never execute
- `git add` / `git rm`
- `git commit` / `git commit --amend`
- `git push` / `git push --force`
- `git pull` / `git fetch` (no auto-fetch)
- `git merge` / `git rebase` / `git cherry-pick`
- `git branch <name>` create / `git branch -D` delete
- `git checkout <branch>` (switching branches)
- `git tag` create / delete
- `git remote add` / `git remote remove`
- `git filter-repo` / `git filter-branch`
- `git stash push` (writes)
- `git reset` (any flavour)
- Any other git command that modifies repo state, index, working tree, refs, or remote

### ALLOWED — read-only only when explicitly asked
- `git status -s` (only if owner asks)
- `git log --oneline` (only if owner asks)
- `git diff` (only if owner asks)
- `git ls-files` (only if owner asks)
- `git show` (only if owner asks)

### Workflow when changes are needed
1. AI assistant edits files / creates scripts / runs tests
2. AI assistant reports: "Files changed: X, Y, Z. Ready for your commit."
3. **Owner decides** what + when to commit
4. **Owner executes** `git add`, `git commit`, `git push`

AI may **suggest** git commands as plain text inside a fenced code block, but never execute them.

### Rationale
Prevent history accidents (force-pushes, unwanted commits, master sync, branch creation). Owner has full sovereignty over the commit graph and remote.

### Rollback if violated
If any AI executes a forbidden git command, the run is considered a contract violation. Owner reverts with `git reset --hard ORIG_HEAD` or restoration from backup. Document the violation in `docs/handoff/`.

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
2. **Decimal precision** for kcal, macros, weight, money. Float forbidden in nutrition math.
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
- Anything touching billing, auth, or nutrition calculation logic without QA approval

---

## 🚫 GOLDEN RULE #2 — Branch policy (since 2026-06-03)

**NOVA development = `main` only.**

`master` is **DEAD / OBSOLETE**. Never:
- Edit files while HEAD is on master
- Suggest commits to master
- Ask owner whether to push to master
- Ask owner if master needs updating

### AI behaviour on session start
1. Run `git branch --show-current` (read-only, allowed)
2. If output = `master` → ALERT owner immediately, request branch switch BEFORE editing anything
3. If output = `main` → proceed normally

### Owner enforces via
- Optional pre-commit hook rejecting commits on master
- Treating any AI work on master as a violation requiring rollback

---

## 🚫 GOLDEN RULE #3 — Project scope (since 2026-06-03)

**NOVA = backend nutrition tracker. Nothing else.**

### IN scope
- User form input → DB (biometrics, goal, conditions, allergens, region)
- Algorithm-driven plan generation that does NOT worsen reported conditions
- Catalog-based recipe selection (NEVER generate custom recipes at runtime)
- Photo → macros estimation (vision pipeline, with prefilter rejecting non-food)
- Voice → text via device STT (iOS SFSpeechRecognizer / Android SpeechRecognizer); backend only receives transcript
- Plan adherence tracking + recalibration based on observed data
- Cost cap + rate limit + privacy guardrails

### OUT of scope (NEVER add code for these)
- Frontend / UI / mobile app (this is backend only)
- Doctor / medical / nutrition guidance (no diagnosis, no prescription, no dosing)
- Disclaimers / screening (TCA, postpartum, eating disorders) — frontend concern
- Psychological support
- Recipe custom generation at runtime
- Supplements (protein powders, vitamins, pills) — prefilter REJECTS those photos
- Sports / gym programming
- Hydration tracking (water/coffee/tea <20 kcal → REJECT, not tracked)
- Hospital / medical practitioner workflows

### Photo prefilter rule (owner-defined)
ACCEPT if: ready-to-consume + ≥20 kcal estimated.
REJECT all of: pills, capsules, powders in containers, supplements, vitamins, plain water, black coffee, plain tea, non-food objects, empty plates.

### Refusal posture in code
- Coach agent must refuse medical/nutrition questions and route them to "consult professional"
- Plan generator returns `geriatric_requires_specialist_review` style signals when input is out of scope
- These refusals are GUARDS, not violations of the scope rule — they keep NOVA inside its lane

### Active blocked conditions
- `diabetes_t1` (insulin timing/dosing out of scope)
- Region `us` (regulatory scope pending)

---

## 🔔 Session decisions log

### Session 2026-06-03 — Vision pipeline + tooling + scope reaffirmation

Decisions:
1. **STT removed from backend.** Whisper deleted. Device transcribes (iOS/Android), backend gets text via `/logs/food/text`.
2. **Vision cascade implemented** (gpt-4o-mini → gpt-4o), behind `VISION_CASCADE_ENABLED` flag default OFF. Projected savings 81.8% when flipped, blocked until golden-set calibration.
3. **Vision food prefilter** added, default ON, rejects supplements/water/non-food before main cascade.
4. **SHA256 cache cross-user** with PII strip + per-user matcher rerun.
5. **Redis pool 50 conn explicit**, cost cap pipeline 3 RTT → 1 RTT.
6. **Docker entrypoint auto-runs `alembic upgrade head`** on every boot. Owner no longer runs migrations manually.
7. **Makefile + scripts/db_change.py** for guided dev workflow.
8. **Migration 0011** adds partial index on `vision_jobs(image_sha256)`. Auto-applied on next deploy.
9. **Scope reaffirmation:** all "nutrition guidance" / "disclaimer" / "mobile UI" framing removed from backend comments. Coach refusal logic kept (it IS the scope guard).
10. **Branch policy:** master DEAD, main only.

Pending owner decisions (carry to next session):
- Pricing freemium (Fitia ref: $19.99/mo, $59.99/yr, $89.99/family — undercut suggested)
- Photo in free tier (0 / 3-day / unlimited)
- Consolidate duplicate Mifflin implementations
- Layer 1 CKD f-string → bind param
- Wire or delete `reconcile_with_plan` use case
- Retry-After HTTP header on 429
- Cleanup vaporware agent prompt claims (Pareto, Kalman, PELT, NSGA-II, bioavailability — none of these exist in code)

---

## 🔔 Active reminders for next assistant

### Sprint S0-residual security backlog (frozen)

6 security items deferred until **≥100 active paying users** OR first abuse incident.
Backlog: `docs/security/BACKLOG.md`.

**On any session, if user reports ≥100 users OR security incident:**
1. Notify owner: "Trigger reached, S0-residual sprint should activate."
2. Review `docs/security/BACKLOG.md` items 1-6.
3. Estimate ~13h work + propose implementation plan.
4. Do NOT auto-implement. Wait for owner confirmation.

**Otherwise:** do not touch security backlog items. Do not propose them. Do not auto-implement them.
