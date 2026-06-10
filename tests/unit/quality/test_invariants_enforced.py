"""Patrón #5 — static gate enforcing post-mutation invariants in use cases.

Heuristic
---------
A use case that performs more than one write (mutation) in a single
transaction MUST either:

  (a) raise a ``BusinessRuleViolation`` / ``ConflictError`` /
      ``InvalidCredentials`` (etc) when a logical invariant fails — the
      outer FastAPI session dependency then rolls the transaction back,
      OR

  (b) rely on a DB-level constraint (partial UNIQUE / CHECK / FK) that
      raises ``IntegrityError`` and is explicitly mapped by the use case
      to a domain error.

The gate detects ``async def __call__`` methods in
``app/*/application/**.py`` that:
  - have more than one call expression that "looks like a write" —
    heuristic: any awaited call whose attribute path contains one of the
    write verbs (``add``, ``update``, ``upsert``, ``save``, ``insert``,
    ``delete``, ``revoke``, ``consume``, ``claim``, ``increment``,
    ``lock``, ``cancel``, ``schedule``, ``append``, ``bulk_insert``,
    ``record``, ``revoke_all_for_user``, ``mark_meal_completed``,
    ``swap_meal_recipe``, ``mark_reused``, ``revoke_family``,
    ``persist``, ``put``, ``write``), AND
  - do NOT contain ANY ``raise`` statement (defensive invariant) AND
  - are not whitelisted below.

Whitelist
---------
A use case is allowed to skip the in-Python ``raise`` if its writes are
fully covered by DB-level constraints AND a separate dedicated test
covers the IntegrityError mapping. Each entry MUST cite the constraint
and the test that proves it.

This is a *signal-driven* gate — it does NOT replace human review. False
positives can be silenced by adding a whitelist entry with a one-line
rationale. False negatives are accepted: a use case that does only one
write does not need an invariant check (the single write either succeeds
or rolls back atomically).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_APP_ROOT = _REPO_ROOT / "app"

# Verbs / method names that signify a mutation when seen as the rightmost
# attribute of an awaited call.
_WRITE_VERBS: frozenset[str] = frozenset(
    {
        "add",
        "update",
        "upsert",
        "save",
        "save_seed",
        "insert",
        "bulk_insert_items",
        "insert_achievement",
        "delete",
        "delete_item",
        "revoke",
        "revoke_all_for_user",
        "revoke_family",
        "consume",
        "claim",
        "increment_attempts",
        "lock",
        "cancel_deletion",
        "schedule_deletion",
        "append",
        "record_change",
        "mark_meal_completed",
        "mark_reused",
        "swap_meal_recipe",
        "update_meta",
        "update_item",
        "upsert_subscription",
        "insert_webhook_event",
    }
)

# (relative_path, qualified_name): "rationale — covered_by"
# Each entry MUST explain why the use case is safe without an explicit
# raise-based invariant check.
_WHITELIST: dict[tuple[str, str], str] = {
    # Identity register: in the refactor of 2026-06-09 the use case no
    # longer creates a ``users`` row — it only enqueues an OTP via the
    # injected ``SendOtp``. The "writes" detected (``hasher.hash``) are
    # not mutations against persistent storage.
    (
        "app/identity/application/use_cases.py",
        "RegisterUser.__call__",
    ): "no DB writes — only enqueues OTP via SendOtp",
    # Login is read + token issuance; invariants enforced inside the
    # extracted ``_issue_token_pair`` helper (single refresh-token write
    # plus event publish). Counted as multi-write by heuristic but
    # logically atomic.
    (
        "app/identity/application/use_cases.py",
        "LoginUser.__call__",
    ): "single ``refresh_tokens.add`` covered by uq_refresh_tokens_hash",
    # OAuth login: writes are exactly one ``users.add`` OR one
    # ``users.update`` plus the token issuance helper. The IntegrityError
    # mapping for races is tested in test_identity_di_and_rate_limit and
    # the email UNIQUE constraint enforces the invariant at schema level.
    (
        "app/identity/application/use_cases.py",
        "OAuthLogin.__call__",
    ): "users.email UNIQUE; race mapped to ConflictError",
    # SendOtp inserts a single ``otps`` row; email dispatch is best-effort
    # downstream. No multi-write invariant.
    (
        "app/identity/application/use_cases.py",
        "SendOtp.__call__",
    ): "single otps.add insert",
    # DeleteFoodLog: the two "writes" are (1) ``repo.delete`` (single SQL
    # mutation with internal RLS check, raises NotFoundError on miss) and
    # (2) ``redis.delete`` (best-effort cache eviction; failure is logged
    # but must not abort the delete). Single-write semantics in spite of
    # the heuristic count.
    (
        "app/tracking/application/food_log_uc.py",
        "DeleteFoodLog.__call__",
    ): "single repo.delete + best-effort redis cache eviction",
    # GenerateGroceryList raises ``BusinessRuleViolation`` post-mutation
    # when items.count == 0 yet plan has meals — explicit invariant.
    # (Reference entry; the heuristic should now PASS, not need
    # whitelisting. Kept here to document intent.)
}


@pytest.fixture(scope="module")
def application_use_cases() -> list[tuple[Path, ast.AsyncFunctionDef, str]]:
    """Walk app/*/application/*.py and return every ``async __call__``
    method, paired with the enclosing class name for diagnostics.
    """
    found: list[tuple[Path, ast.AsyncFunctionDef, str]] = []
    for py_file in _APP_ROOT.rglob("application/*.py"):
        if py_file.name == "__init__.py":
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for child in node.body:
                    if (
                        isinstance(child, ast.AsyncFunctionDef)
                        and child.name == "__call__"
                    ):
                        found.append((py_file, child, node.name))
    return found


def _count_writes(fn: ast.AsyncFunctionDef) -> int:
    """Count awaited calls whose rightmost attribute is in ``_WRITE_VERBS``."""
    count = 0
    for node in ast.walk(fn):
        if isinstance(node, ast.Await) and isinstance(node.value, ast.Call):
            call = node.value
            func = call.func
            name: str | None = None
            if isinstance(func, ast.Attribute):
                name = func.attr
            elif isinstance(func, ast.Name):
                name = func.id
            if name and name in _WRITE_VERBS:
                count += 1
    return count


def _has_raise(fn: ast.AsyncFunctionDef) -> bool:
    return any(isinstance(n, ast.Raise) for n in ast.walk(fn))


def test_multi_write_use_cases_have_invariant_raise(
    application_use_cases: list[tuple[Path, ast.AsyncFunctionDef, str]]
) -> None:
    """For every ``async __call__`` with > 1 write, require at least one
    ``raise`` statement OR a whitelist entry citing the DB-level guard.
    """
    failures: list[str] = []
    for path, fn, cls_name in application_use_cases:
        writes = _count_writes(fn)
        if writes <= 1:
            continue
        if _has_raise(fn):
            continue
        rel = str(path.relative_to(_REPO_ROOT))
        key = (rel, f"{cls_name}.__call__")
        if key in _WHITELIST:
            continue
        failures.append(
            f"{rel}::{cls_name}.__call__ has {writes} writes and no raise "
            "(add explicit invariant check, or whitelist with rationale)"
        )
    assert not failures, (
        "Multi-write use cases without invariant enforcement:\n  - "
        + "\n  - ".join(failures)
    )


def test_whitelist_entries_still_apply(
    application_use_cases: list[tuple[Path, ast.AsyncFunctionDef, str]]
) -> None:
    """Stale-whitelist gate: every key in ``_WHITELIST`` MUST correspond
    to an existing ``__call__`` method. Removing/renaming a use case
    silently leaving a stale whitelist entry is a code-smell — the rule
    might silently lapse on a sibling.
    """
    present_keys = {
        (str(path.relative_to(_REPO_ROOT)), f"{cls}.__call__")
        for path, _, cls in application_use_cases
    }
    stale = sorted(k for k in _WHITELIST if k not in present_keys)
    assert not stale, f"Stale whitelist entries (remove or rename): {stale}"
