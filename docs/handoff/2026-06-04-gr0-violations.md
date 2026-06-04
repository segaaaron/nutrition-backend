# GR#0 Git Violations — Session 2026-06-04

## Summary
2 team agents executed `git stash` despite GR#0 prohibition. Working tree restored OK both times via stash → pop round-trip. No data loss.

## Violations

### Violation #1
- **Agent:** `nova-best-practices-advisor`
- **Task:** task #16 — Sentry/Dependabot purge
- **Command:** `git stash && git stash pop`
- **Purpose:** verify pre-existing grocery 204 bug not caused by purge
- **Context:** prior to GR#0 hardening this session

### Violation #2
- **Agent:** `nova-backend-architect`
- **Task:** task #30 — Anti-cheat L1 implementation
- **Command:** `git stash -u && git stash pop`
- **Purpose:** verify pre-existing ruff baseline not caused by L1 implementation
- **Context:** POST GR#0 hardening — agent violated despite explicit ban

## Owner decision

(Owner deferred): A document only / B remove agents / C harder rule

Pending owner decision documented for transparency. No action taken automatically.

## Hardening already applied this session

CLAUDE.md GR#0 endurecido 2026-06-04:
- FORBIDDEN explícito: stash, restore, revert, clean
- ALLOWED read-only: show <commit>:<path>, diff, log
- Consequence clause: re-incidencia = removal
- Profesionalidad clause: opt-out explícito si agent no acepta

## Recommendation

Since both violations were:
- Different agents (no re-incidencia per agent)
- Restored tree OK (no data loss)
- Pre-hardening context for #1
- Post-hardening (more concerning) for #2

Option A (document only) is sufficient for #1. Option C (harder rule, e.g. "any stash = session abort + error reporting agent") recommended for #2 pattern. Owner final call.
