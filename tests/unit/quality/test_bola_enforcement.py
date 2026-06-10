"""OWASP API1 — static AST enforcement of BOLA (Broken Object Level Auth).

For every FastAPI endpoint exposed under ``app/**/presentation/router*.py``
(and ``app/**/router.py``) that includes a path placeholder of the shape
``{xxx_id}`` / ``{xxx}``, this test verifies that the handler body contains
at least one of the recognised ownership-enforcement patterns:

  - ``assert_owns(...)``                        — central allowlist helper
  - ``ensure_owner(...)``                       — grocery-specific helper
  - Any call passing ``user_id=current_user``   — use case enforces internally
  - Any call passing ``current_user`` positionally to a repo/use case
    constructor that, by convention, must include ``user_id`` filtering

Endpoints that are intentionally public (no user-owned resource behind the
ID) must be explicitly declared in ``PUBLIC_ENDPOINTS``. Adding a new
endpoint with a path ID that fails BOTH checks (no ownership call AND not
whitelisted) will cause this test to fail loudly — by design.

This is a *belt and braces* defence layered on top of the existing
unit/integration tests in ``tests/unit/test_bola_audit.py`` and the
per-endpoint behavioural tests across each bounded context.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
APP_ROOT = REPO_ROOT / "app"

# Path placeholders that point at a non-user-owned resource (catalog, OAuth
# provider slug, enum-bound literal, etc.) — exempt from BOLA enforcement.
# Format: (method, path_template) tuples.
PUBLIC_ENDPOINTS: set[tuple[str, str]] = {
    # OAuth provider name in the path (apple / google), not a resource id.
    ("POST", "/auth/oauth/{provider}"),
    # Recipes & foods catalog (curated, multi-tenant read-only).
    ("GET", "/recipes/{recipe_id}"),
    ("GET", "/foods/barcode/{ean}"),
    # Shared grocery list (auth via signed share token, validated inline).
    ("GET", "/grocery-lists/{list_id}/shared"),
    # `item` is a `Literal["breakfast","lunch","dinner","water"]` slot —
    # the row keyed by (user_id, date, item) is upserted using `current_user`
    # from the JWT in the handler body. Not a foreign resource id.
    ("POST", "/goals/today/{item}/toggle"),
}

# Function names that, when called inside a handler, constitute a valid
# ownership check.
_OWNERSHIP_CALLS = frozenset({"assert_owns", "ensure_owner"})


def _iter_router_files() -> list[Path]:
    """Every Python module in the codebase that registers FastAPI routes.

    Covers three conventions present in the repo:
      - ``app/<ctx>/presentation/router.py``
      - ``app/<ctx>/presentation/<feature>_router.py`` / ``<feature>.py``
        (e.g. ``goals_today.py``, ``food_log_router.py``)
      - ``app/<ctx>/router.py`` (top-level routers — grocery, billing)
    """
    paths: set[Path] = set()
    for pattern in ("router*.py", "*_router.py"):
        for p in APP_ROOT.rglob(pattern):
            if "__pycache__" in p.parts:
                continue
            paths.add(p)
    # Sweep every presentation/*.py to catch unusual filenames.
    for p in APP_ROOT.rglob("presentation/*.py"):
        if "__pycache__" in p.parts or p.name == "__init__.py":
            continue
        paths.add(p)
    return sorted(paths)


def _decorator_endpoints(
    decorator: ast.expr,
) -> list[tuple[str, str]]:
    """Return list of (METHOD, PATH) pairs declared by a single decorator.

    Handles ``@router.get("/x")``. The path may be a positional ``ast.Constant``
    string. Returns empty list when the decorator does not declare an HTTP
    route or when the path is not a static string literal (we cannot reason
    about dynamic paths statically — those should be refactored).
    """
    if not isinstance(decorator, ast.Call):
        return []
    func = decorator.func
    if not isinstance(func, ast.Attribute):
        return []
    method = func.attr.upper()
    if method not in {"GET", "POST", "PATCH", "PUT", "DELETE"}:
        return []
    # First positional arg is the path string.
    if not decorator.args:
        return []
    first = decorator.args[0]
    if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
        return []
    return [(method, first.value)]


def _path_has_placeholder(path: str) -> bool:
    return "{" in path and "}" in path


def _handler_calls_ownership_check(fn: ast.AsyncFunctionDef | ast.FunctionDef) -> bool:
    """True iff the handler body shows evidence of BOLA enforcement.

    Recognised patterns (any one suffices):
      a) Call to ``assert_owns`` or ``ensure_owner``.
      b) Any keyword argument ``user_id=current_user`` on any call.
      c) Any call whose argument list contains a bare ``current_user``
         positional reference — used by repositories like
         ``SqlConversationRepository(session).delete(conv_id, current_user)``.
      d) Inline comparison ``... != current_user`` or ``current_user != ...``
         (and ``==`` equivalents) — used by handlers that fetch ownership
         via raw SQL and compare in Python, e.g. grocery.get_grocery_list.
    """
    for node in ast.walk(fn):
        # (d) inline comparison guard.
        if isinstance(node, ast.Compare):
            operands = [node.left, *node.comparators]
            if any(isinstance(o, ast.Name) and o.id == "current_user" for o in operands):
                return True
        if not isinstance(node, ast.Call):
            continue
        # (a) Named ownership helpers.
        callee = node.func
        if isinstance(callee, ast.Name) and callee.id in _OWNERSHIP_CALLS:
            return True
        if isinstance(callee, ast.Attribute) and callee.attr in _OWNERSHIP_CALLS:
            return True
        # (b) keyword user_id=current_user.
        for kw in node.keywords:
            if kw.arg != "user_id":
                continue
            v = kw.value
            if isinstance(v, ast.Name) and v.id == "current_user":
                return True
        # (c) positional current_user.
        for arg in node.args:
            if isinstance(arg, ast.Name) and arg.id == "current_user":
                return True
    return False


def _collect_endpoints() -> list[tuple[Path, int, str, str, ast.AsyncFunctionDef | ast.FunctionDef]]:
    """Return [(file, lineno, method, path, handler_fn), ...] for every
    declared HTTP route across the codebase."""
    results: list[tuple[Path, int, str, str, ast.AsyncFunctionDef | ast.FunctionDef]] = []
    for path_file in _iter_router_files():
        tree = ast.parse(path_file.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
                continue
            for dec in node.decorator_list:
                for method, route in _decorator_endpoints(dec):
                    results.append((path_file, node.lineno, method, route, node))
    return results


def test_every_endpoint_with_path_id_enforces_ownership() -> None:
    """Static guarantee: any endpoint exposing ``{xxx}`` in its path must
    either invoke an ownership helper OR pass ``user_id=current_user`` to a
    use case — UNLESS it is explicitly whitelisted as public.

    Failure mode: developer adds a new endpoint with a path parameter and
    forgets BOLA enforcement → this test fails with a precise pointer to
    the offending function. Whitelist requires deliberate code review.
    """
    endpoints = _collect_endpoints()
    assert endpoints, "no endpoints discovered — AST walk regressed"

    violations: list[str] = []
    for file_path, lineno, method, route, handler in endpoints:
        if not _path_has_placeholder(route):
            continue
        if (method, route) in PUBLIC_ENDPOINTS:
            continue
        if _handler_calls_ownership_check(handler):
            continue
        rel = file_path.relative_to(REPO_ROOT)
        violations.append(
            f"  {rel}:{lineno}  {method} {route}  → handler "
            f"`{handler.name}` has no detectable ownership check "
            f"(assert_owns / ensure_owner / user_id=current_user / "
            f"positional current_user). Either add a check or whitelist "
            f"explicitly in PUBLIC_ENDPOINTS."
        )

    if violations:
        msg = "BOLA enforcement missing on:\n" + "\n".join(violations)
        pytest.fail(msg)


def test_public_endpoints_whitelist_entries_are_reachable() -> None:
    """Sanity check: every whitelisted (method, path) tuple corresponds to a
    real endpoint in the codebase. Catches stale entries after refactors.
    """
    declared = {(m, r) for _f, _ln, m, r, _h in _collect_endpoints()}
    stale = PUBLIC_ENDPOINTS - declared
    assert not stale, (
        "PUBLIC_ENDPOINTS contains entries that no longer exist in any "
        f"router: {sorted(stale)}. Remove or update them."
    )
