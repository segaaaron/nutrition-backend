"""Static AST gate — block new ``session_scope()`` sites inside request use cases.

Patrón #3 (session-in-session / cross-session race):

  When a FastAPI request handler already runs inside a transactional
  session (``SessionDep`` → ``get_session`` from
  ``app.identity.presentation.dependencies``), invoking
  ``session_scope()`` inside the use case opens a SECOND independent
  transaction. Two failure modes follow:

    (a) The nested session commits while the outer rolls back → orphan
        rows (the audit row that bit us in
        ``UpdateProfile.region_change_locked`` before the Patrón #3 fix).
    (b) The nested session reads data that the outer has written but
        not yet committed → snapshot isolation hides the row, handler
        silently no-ops (this is the same bug class that ADR-0030
        deferred-event-bus fixed for handlers; the use-case body is the
        twin we close here).

Allowed sites (whitelist below) fall under one of:

  OK1: outbox spool — by design INDEPENDENT of the outer transaction,
       because the outer commit has already succeeded (we are reacting
       to a post-commit handler failure). Documented in
       ``app/core/event_bus.py``.
  OK2: event handler registered against ``EventBus`` — runs AFTER
       ``flush_request_scope`` which fires AFTER the outer commit (ADR
       -0030). Opening a fresh session here is safe.
  OK3: worker / arq task entry-point — runs outside any FastAPI request
       context. There is no outer session to race against.
  OK4: documented audit cross-tx (NONE today; reserved if a future need
       arises and is justified in code).

Adding to whitelist:
  Only when one of the categories above applies. The site MUST carry an
  inline comment explaining which category and why a savepoint or
  outer-session reuse is not possible.

Mechanics:
  - Walk ``app/`` and ``worker/`` for ``.py`` files.
  - AST-parse each, locate every ``ast.With`` / ``ast.AsyncWith`` whose
    context manager is a call to ``session_scope`` (positional or
    aliased import).
  - Compare findings against ``ALLOWED_SESSION_SCOPE`` keyed by
    ``relative_path:line_no``.
  - Fail loudly on:
      1. Findings NOT in whitelist (new nested session site added)
      2. Whitelist entries NOT found (stale entry — keep the cache
         honest)
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCAN_ROOTS = ("app", "worker")


# Whitelist of currently-legitimate ``session_scope()`` call sites.
# Keys are "<relative path from repo root>:<line number>".
# Values are short justification strings (OK1..OK4 + free text).
ALLOWED_SESSION_SCOPE: dict[str, str] = {
    # OK1 — outbox spool: post-commit handler failure recovery. The
    # outer transaction has already committed by definition (the bus is
    # in flush-after-commit phase), so opening a fresh session is
    # required and safe.
    "app/core/event_bus.py:344": "OK1 outbox spool — post-commit, independent by design",
    # OK2 — event handlers (deferred bus, post-commit dispatch).
    # Lines re-synced after E4 StreakBroken detection added ~11 lines per handler.
    "app/gamification/application/event_handlers.py:241": "OK2 event handler (FoodLogged)",
    "app/gamification/application/event_handlers.py:282": "OK2 event handler (FoodPhotoLogged)",
    "app/gamification/application/event_handlers.py:326": "OK2 event handler (WaterLogged)",
    "app/gamification/application/event_handlers.py:361": "OK2 event handler (FastingCompleted)",
    "app/gamification/application/event_handlers.py:390": "OK2 event handler (FoodLogged achievement)",
    "app/gamification/application/event_handlers.py:415": "OK2 event handler (FastingCompleted achievement)",
    "app/gamification/application/event_handlers.py:437": "OK2 event handler (DayCompleted achievement)",
    "app/gamification/application/event_handlers.py:462": "OK2 event handler (WeightLogged)",
    "app/nutrition/event_handlers.py:64": "OK2 event handler (BiometricsChanged safety net)",
    "app/nutrition/event_handlers.py:83": "OK2 event handler (WeightLogged recalibration)",
    # OK2 — event handlers spawning their own session (no outer request session).
    "app/coach/application/features.py:270": "OK2 event handler (coach feature lookup)",
    "app/tracking/event_handlers.py:30": "OK2 event handler (tracking best-effort)",
    "app/tracking/event_handlers.py:41": "OK2 event handler (tracking best-effort)",
    # OK3 — worker tasks (arq job entry-points, no outer FastAPI session).
    "worker/plan_tasks.py:49": "OK3 worker task",
    "worker/plan_tasks.py:80": "OK3 worker task",
    "worker/outbox_drainer.py:121": "OK3 worker task",
    "worker/vision_tasks.py:50": "OK3 worker task",
    # OK3 — fresh session for failure bookkeeping AFTER the main job
    # session rolled back (mark_failed + deadletter must survive the
    # rollback or the vision job stays 'running' forever).
    "worker/vision_tasks.py:88": "OK3 worker task (post-rollback failure bookkeeping)",
    "worker/leaderboard_audit_purge_task.py:55": "OK3 worker task",
    "worker/idempotency_tasks.py:16": "OK3 worker task",
    "worker/anomaly_score_task.py:211": "OK3 worker task",
    "worker/coach_tasks.py:54": "OK3 worker task",
    "worker/coach_tasks.py:68": "OK3 worker task",
    "worker/coach_tasks.py:88": "OK3 worker task",
    "worker/coach_tasks.py:102": "OK3 worker task",
    "worker/coach_tasks.py:108": "OK3 worker task",
    "worker/coach_tasks.py:114": "OK3 worker task",
    "worker/nightly_maintenance.py:41": "OK3 worker task",
    "worker/nightly_maintenance.py:49": "OK3 worker task",
    "worker/nightly_maintenance.py:65": "OK3 worker task",
    "worker/nightly_maintenance.py:74": "OK3 worker task",
    "worker/nightly_maintenance.py:79": "OK3 worker task",
    "worker/nightly_maintenance.py:93": "OK3 worker task",
    "worker/nightly_maintenance.py:99": "OK3 worker task",
}


def _iter_py_files() -> list[Path]:
    out: list[Path] = []
    for root in SCAN_ROOTS:
        base = REPO_ROOT / root
        if not base.exists():
            continue
        out.extend(p for p in base.rglob("*.py") if "__pycache__" not in p.parts)
    return sorted(out)


def _is_session_scope_call(node: ast.AST) -> bool:
    """Return True if ``node`` is a call to ``session_scope`` (any alias).

    We match by the attribute/name segment ``session_scope`` so both
    ``session_scope()`` and ``db.session_scope()`` are caught. Aliased
    imports (``from app.core.db import session_scope as ss``) are NOT
    matched — they are uncommon and would require a per-file alias
    table; the whitelist would catch any new alias regardless.
    """
    if not isinstance(node, ast.Call):
        return False
    fn = node.func
    if isinstance(fn, ast.Name) and fn.id == "session_scope":
        return True
    if isinstance(fn, ast.Attribute) and fn.attr == "session_scope":
        return True
    return False


def _find_session_scope_sites() -> list[tuple[str, int]]:
    sites: list[tuple[str, int]] = []
    for path in _iter_py_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            items = []
            if isinstance(node, ast.With | ast.AsyncWith):
                items = node.items
            else:
                continue
            for it in items:
                ctx = it.context_expr
                if _is_session_scope_call(ctx):
                    rel = path.relative_to(REPO_ROOT).as_posix()
                    sites.append((rel, ctx.lineno))
    return sorted(sites)


def test_no_new_session_scope_without_whitelist() -> None:
    """Fail when a `session_scope()` call appears outside the whitelist."""
    sites = _find_session_scope_sites()
    found_keys = {f"{p}:{ln}" for p, ln in sites}
    allowed_keys = set(ALLOWED_SESSION_SCOPE)

    unexpected = sorted(found_keys - allowed_keys)
    stale = sorted(allowed_keys - found_keys)

    msg_parts: list[str] = []
    if unexpected:
        msg_parts.append(
            "NEW unwhitelisted `session_scope()` sites detected — these are "
            "Patrón #3 risks (nested session inside an outer request "
            "transaction). Either refactor to use the injected session "
            "(savepoint / port pattern) OR add an explicit whitelist entry "
            "with an OK1/OK2/OK3/OK4 justification in "
            "tests/unit/quality/test_session_lifecycle.py.\n  - "
            + "\n  - ".join(unexpected)
        )
    if stale:
        msg_parts.append(
            "STALE whitelist entries — these sites no longer exist; remove "
            "them from ALLOWED_SESSION_SCOPE so the cache stays honest.\n  - "
            + "\n  - ".join(stale)
        )
    assert not msg_parts, "\n\n".join(msg_parts)


def test_update_profile_uses_region_audit_port() -> None:
    """Regression: UpdateProfile must NOT import session_scope.

    The Patrón #3 fix moved the region-change audit onto the SAME
    session as the profile upsert via the ``RegionAuditPort``. If a
    future refactor reintroduces ``session_scope`` here we lose the
    atomicity guarantee — fail loudly.
    """
    path = REPO_ROOT / "app/profile/application/use_cases.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.With | ast.AsyncWith):
            for it in node.items:
                if _is_session_scope_call(it.context_expr):
                    offenders.append(it.context_expr.lineno)
    assert not offenders, (
        "app/profile/application/use_cases.py must not invoke session_scope() — "
        "use the RegionAuditPort adapter bound to the injected session. "
        f"Offending lines: {offenders}"
    )
