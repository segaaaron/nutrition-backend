# Tech Debt Audit — 2026-06-04

**Scope:** Cleanup pass per owner directive. Vaporware retry in agent prompts + pre-existing mypy/ruff debt.

**Constraints honoured:**
- GR#0 git lockdown (no git commands executed)
- GR#1 team-only (acted as `nova-best-practices-advisor`)
- Branch `main`
- Minimal surgery; no mass refactor

---

## Verification baseline

| Check | Before | After |
|---|---|---|
| `pytest tests/unit/` | 851 pass | **851 pass** |
| `ruff check app/ --statistics` total | 85 | **66** |
| `ruff S608` | 6 | **0** |
| `ruff S110` | 13 | **0** |
| `mypy --strict` on 4 target files | 11 errors | **0 errors** |

---

## Part 1 — Vaporware retry (BLOCKED by sandbox)

`Edit` tool denied on `.claude/agents/*.md` (sandbox permission, not a CLAUDE.md rule). Probe edit on `nova-nutrition-algorithms-expert.md` returned `Permission to use Edit has been denied`.

**Status:** **DEFERRED to owner manual edit.** Patches below — owner copy/paste.

### File: `.claude/agents/nova-nutrition-algorithms-expert.md`

Each block shows existing line + recommended replacement. Add `(PLANNED, not implemented)` flag or remove the claim.

#### L3 (description frontmatter)

The description's `<example>` block currently asserts `PELT` plateau detection as if implemented:

> OLD (within description string):
> `detecta plateau via PELT en weight_logs 21d, aplica adaptive thermogenesis correction −7% TDEE, ajusta kcal target −150kcal, GL<10/meal hard filter, fiber min 25g, Pareto rank con prep_time preference`

> NEW:
> `detecta plateau via OLS slope sobre weight_logs 21d (PELT planned, no implementado), ajusta kcal target −150kcal, GL<10/meal hard filter, fiber min 25g, weighted-sum rank con prep_time preference (Pareto/NSGA-II planned, no implementado)`

#### L126

> OLD: `- Cultural fit: cosine(user.region_vector, recipe.region_vector)`
> NEW: `- Cultural fit: cosine(user.region_vector, recipe.region_vector) *(PLANNED — not implemented; current: hard region SQL filter)*`

#### L127

> OLD: `- Taste EMA: leveraged from food_logs feedback`
> NEW: `- Taste EMA: leveraged from food_logs feedback *(PLANNED — not implemented)*`

#### L128

> OLD: `- Variety penalty: cosine_distance(recipe_embedding, last_14d_centroid)`
> NEW: `- Variety penalty: cosine_distance(recipe_embedding, last_14d_centroid) *(PLANNED — not implemented; current: no-repeat-within-4d rule only)*`

#### L167

> OLD: `| food_logs (30d) | NO | skip taste EMA, use cultural defaults |`
> NEW: `| food_logs (30d) | NO | skip taste EMA (planned), use cultural defaults |`

#### L179

> OLD: `| hypertension | DASH adherence ≥0.7, sodium <1500mg, K ≥4700mg, Mg ≥400mg | conditions, region (LatAm sodium baseline high) |`
> NEW: `| hypertension | sodium <1500mg, K ≥4700mg, Mg ≥400mg (DASH adherence score PLANNED) | conditions, region (LatAm sodium baseline high) |`

#### L183

> OLD: `| ischemic_heart_disease | Mediterranean adherence ≥0.7, sat_fat <7%, omega-3 ≥500mg | conditions |`
> NEW: `| ischemic_heart_disease | sat_fat <7%, omega-3 ≥500mg (Mediterranean adherence score PLANNED) | conditions |`

#### L190

> OLD: `| ibs | FODMAP-low ranking, exclude high-FODMAP triggers | conditions |`
> NEW: `| ibs | exclude high-FODMAP triggers (FODMAP-low scoring rank PLANNED) | conditions |`

#### L254

> OLD: `"history.food_logs.last_14d (n=38) → taste EMA applied"`
> NEW: `"history.food_logs.last_14d (n=38) → cultural defaults applied (taste EMA planned, not yet computed)"`

#### L269

> OLD (inside SÍ-hace list): `- Bioavailability corrections`
> NEW: REMOVE the line entirely, OR replace with `- Bioavailability corrections *(PLANNED — not in code)*`

#### L312

> OLD: `- Variety penalty embedding cosine = O(N_history × dim) where dim=1536 → batch operation, <50ms.`
> NEW: `- Variety penalty embedding cosine = PLANNED, not implemented. Current: no-repeat-within-4d rule (O(1)).`

### File: `.claude/agents/nova-backend-architect.md`

Audited — L15 + L29 already carry "NOT YET implemented" / "PLANNED, not implemented" flags. No further edits required.

---

## Part 2 — Pre-existing tech debt

### A. mypy --strict errors (11 → 0, FIXED inline)

| File | Line | Error | Fix applied |
|---|---|---|---|
| `app/identity/presentation/dependencies.py` | 116 | missing return type on `require_role` | Added `-> Callable[..., Awaitable[UUID]]` |
| `app/identity/presentation/dependencies.py` | 151 | `dict` missing generic args | `dict` → `dict[str, Any]` |
| `app/identity/presentation/dependencies.py` | 172 | unused `# type: ignore[assignment]` | Removed |
| `app/identity/presentation/dependencies.py` | 196 | untyped param `redis=None` | `redis: Any = None` |
| `app/identity/presentation/dependencies.py` | 198 | `dict` missing generic args | `dict` → `dict[str, Any]` |
| `app/grocery/router.py` | 40 | untyped param `gl` | `gl: GroceryList` |
| `app/grocery/router.py` | 214 | `dict` missing generic args | `dict` → `dict[str, Any]` |
| `app/main.py` | 52 | untyped `dispatch` + unused ignore | Added `Callable[[Request], Awaitable[Response]]` signature, removed `# type: ignore[override]` |
| `app/identity/application/use_cases.py` | 470 | `dict` missing generic args | `dict` → `dict[str, Any]` (imported `Any`) |

All fixes are pure annotations — no runtime behaviour change. Verified by 851 unit tests still passing.

### B. ruff S608 hardcoded-sql-expression (6 → 0, FIXED inline)

**Root cause:** existing `# noqa: S608` comments were anchored to the wrong line. ruff anchors S608 to the **start of the f-string literal** (the `f"""` line) and reads the noqa on the **last physical line of the string** (the closing `"""` line). Existing noqas were on the surrounding `)` or `.first()` line — silently ignored.

All 6 are legitimate (no user input reaches the SQL string), so the fix was to move the `# noqa: S608` onto the trailing `"""` line of each f-string. Files touched:

- `app/coach/application/chat_message.py:212`
- `app/coach/application/context_builder.py:151`
- `app/grocery/repository.py:136`
- `app/tracking/infrastructure/fasting_repository.py:123`
- `app/tracking/presentation/progress_router.py:109`
- `app/vision/infrastructure/food_matcher.py:111`

All retain a one-line justification (vec_lit float-only, or `where`/`sets` from literal fragments only, values bound via `:params`).

### C. ruff S110 try-except-pass (13 → 0, FIXED inline)

All 13 are legitimate best-effort patterns (cache misses, optional duck-typed imports, tracker-must-not-raise). Each already had `# noqa: BLE001` with a comment; added `,S110` to the same noqa and clarified the comment to state the fall-through behaviour.

| File:line | Pattern |
|---|---|
| `app/core/error_tracker.py:84,95,125,130` | Tracker must never raise; best-effort state read |
| `app/gamification/application/use_cases.py:131` | Celebration queue best-effort |
| `app/identity/application/use_cases.py:235` | Invalid/expired token must not block logout |
| `app/nutrition/event_handlers.py:89` | Optional duck-typed subscription |
| `app/plan/application/taste_profile.py:48` | Cache miss → rebuild |
| `app/plan/infrastructure/openai_coherence_client.py:101` | Cache miss → rebuild |
| `app/tracking/event_handlers.py:17` | Cache miss acceptable |
| `app/tracking/infrastructure/food_log_repository.py:186,241` | Aggregate table optional; fallback below |
| `app/tracking/infrastructure/repositories.py:108` | Aggregate table optional; fallback below |

### D. Remaining 66 ruff findings (DEFERRED — owner priority call)

Breakdown by rule (no fixes applied; owner decides post-launch priority):

| Count | Rule | Note |
|---|---|---|
| 19 | PLR0913 | too-many-arguments — mostly use-case `__call__` signatures; refactor = dataclass param object |
| 16 | E501 | line-too-long — cosmetic; `black` may already wrap these |
| 12 | PLW0603 | global-statement — module-level singletons (`_client`, `_redis`); standard FastAPI pattern |
| 9 | B008 | function-call-in-default-argument — FastAPI `Depends(...)` idiom; consider `# noqa` blanket |
| 2 | I001 | unsorted-imports — auto-fixable with `ruff check --fix` |
| 2 | PLR0915 | too-many-statements — long use case bodies |
| 2 | UP038 | non-pep604-isinstance — auto-fixable |
| 1 | S112 | try-except-continue |
| 1 | B007 | unused-loop-control-variable |
| 1 | B023 | function-uses-loop-variable |
| 1 | PLR0911 | too-many-return-statements |

**Recommendation:** owner runs `.venv/bin/ruff check app/ --fix` post-launch to auto-clear 4 of these (I001 ×2, UP038 ×2). The rest are non-blocking style preferences.

---

## Files modified this session

```
app/coach/application/chat_message.py
app/coach/application/context_builder.py
app/core/error_tracker.py
app/gamification/application/use_cases.py
app/grocery/repository.py
app/grocery/router.py
app/identity/application/use_cases.py
app/identity/presentation/dependencies.py
app/main.py
app/nutrition/event_handlers.py
app/plan/application/taste_profile.py
app/plan/infrastructure/openai_coherence_client.py
app/tracking/event_handlers.py
app/tracking/infrastructure/fasting_repository.py
app/tracking/infrastructure/food_log_repository.py
app/tracking/infrastructure/repositories.py
app/tracking/presentation/progress_router.py
app/vision/infrastructure/food_matcher.py
```

18 files. Net diff: type annotations + noqa relocations. Zero runtime behaviour change.

## Pending owner actions

1. Manually apply the 11 Part-1 patches to `.claude/agents/nova-nutrition-algorithms-expert.md` (sandbox blocked the AI from doing it).
2. Decide whether to run `ruff --fix` for the 4 trivially-fixable findings.
3. Stage + commit per GR#0 — AI did not touch git.
