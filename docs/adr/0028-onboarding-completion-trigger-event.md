# ADR-0028 — Onboarding completion trigger moves to PlanCreated event

- **Status:** Accepted
- **Date:** 2026-06-05
- **Decision owner:** Miguel Ángel Saravia
- **Supersedes / amends:** N/A (refines `CompleteOnboarding` behaviour shipped in S0)
- **Related events:** `app/plan/domain/events.py::PlanCreated`, `app/profile/domain/events.py::OnboardingCompleted`

## Context

The iOS MVP onboarding flow renders a single multi-screen form and ends in
a **single CTA** ("Crear mi plan con NOVA →") that triggers two backend
calls in series:

1. `POST /me/onboarding`
2. `POST /plans`

Previously `CompleteOnboarding` set `profile.onboarding_completed = True`
on call 1. If call 2 failed (timeout, validation, cost-cap, segment
rejection) the user landed in a half-completed state from their
perspective — the flag claimed completion but no plan existed.

Additionally, the iOS MVP form does **not** ask `dietary_pattern`. The
field was required on the schema, so iOS clients had to hard-code it.

## Decisions

### D1 — `dietary_pattern` becomes optional, defaults to `omnivore`

- Schema `OnboardingRequest.dietary_pattern` is now
  `DietaryPattern | None = Field(default=None, ...)`.
- `CompleteOnboarding` defaults missing values to `"omnivore"` and emits a
  structured warning log `dietary_pattern_defaulted_to_omnivore` with
  `user_id` + `goal` only (PII-safe).
- Vegan users who silently default to `omnivore` will receive
  meat-containing recipes until they call `PATCH /me`. iOS clients
  **should** add a dietary-pattern screen post-MVP.

### D5 — Flag flips on `PlanCreated`, not on `/me/onboarding`

- Remove `profile.onboarding_completed = True` from `CompleteOnboarding`.
- Subscribe a profile-side handler to `PlanCreated`; on first dispatch it
  performs `UPDATE profile SET onboarding_completed = true` (idempotent).
- `OnboardingCompleted` domain event is **still published** from
  `CompleteOnboarding` so notifications + gamification consumers do not
  regress.

### Cross-context coupling

Subscribing the **Profile** bounded context to a **Plan** bounded-context
event is intentional per DDD: domain events are the public contract
between bounded contexts. The reverse direction (Plan calling Profile
synchronously) would be the violation.

### In-process EventBus caveat

`app/core/event_bus.py` is a per-process singleton. The API process and
the Arq worker process therefore own **two distinct buses**. Plan
generation runs inside the worker, so the handler MUST be registered in:

- `app/main.py` lifespan (API process) — covers any future in-process
  plan flows, plus tests that hit the API directly.
- `worker/main.py::on_startup` (Arq worker process) — covers the actual
  production path where `POST /plans` enqueues an Arq job that publishes
  `PlanCreated` inside the worker.

Failing to register in either side leaves the flag permanently False for
that path.

### Idempotency + race safety

- Handler reads `profile.onboarding_completed`; if True, returns without a
  DB write. Re-generations of plans do not cause extra writes.
- Two concurrent `PlanCreated` events for the same user converge to
  `True`. Arq enforces single-job-per-idempotency-key, so concurrent
  dispatch is theoretical, not a production path.

### Failure semantics

- Plan generation failure ⇒ no `PlanCreated` ⇒ flag stays `False` ⇒ the
  user is correctly treated as "still onboarding".
- Handler swallows + logs exceptions (`profile.flip_failed`) so a
  transient DB error does not cancel sibling subscribers on the bus.

## Consequences

### Positive

- "Onboarding completed" matches the user-facing UX (no plan = not done).
- Failure of `POST /plans` no longer leaves a bogus completion flag.
- iOS MVP can ship without a dietary-pattern screen.

### Negative / risks

- One additional DB write per first plan creation (acceptable: O(1)).
- Two subscriber registration points to maintain (API + Worker).
- Vegan default risk (mitigated by warning log + `PATCH /me` escape).

## Alternatives considered

- **Keep flag flip in `/me/onboarding`, accept the failure inconsistency.**
  Rejected: contract violation from the user's perspective.
- **Combined `POST /onboarding-and-plan` endpoint.** Rejected: bloats the
  API surface; the two operations have different idempotency semantics,
  cost-cap rules, and retry strategies.
- **Make iOS persist a local "needs plan" flag and retry.** Rejected:
  pushes server-of-record state into the client.

## Test coverage

- Unit: `tests/unit/profile/test_event_handler_flip.py`
- Unit: `tests/unit/profile/test_complete_onboarding.py`
- Unit: `tests/unit/profile/test_dietary_pattern_default.py`
- Integration: `tests/integration/test_onboarding_to_plan_flow.py`
