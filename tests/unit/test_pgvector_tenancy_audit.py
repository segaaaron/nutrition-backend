"""pgvector tenancy regression guard (OWASP API1 — vector flavour).

Static test: scans SQLAlchemy models for tables containing pgvector `Vector`
columns. Each such table must EITHER:
  - have a `user_id` column (per-user tenancy), OR
  - be explicitly listed in GLOBAL_CATALOG_TABLES.

Fails if a new vector model is introduced without classification.

See docs/security/pgvector-tenancy.md for the policy.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from collections.abc import Iterable

# Tables that legitimately have no per-user tenancy: shared catalogs.
GLOBAL_CATALOG_TABLES = {
    "recipes",
    "recipe_components",
    "foods",
    "ingredients",
    "i18n_translations",
    "coach_faq",  # canned coach answers shared across all users
}


def _has_user_id(cols) -> bool:
    return any(c.name == "user_id" for c in cols)


def _has_vector_column(cols) -> bool:
    for c in cols:
        # Avoid hard dep on pgvector type during static scan — match by string.
        type_name = type(c.type).__name__.lower()
        if "vector" in type_name:
            return True
    return False


def _all_model_classes() -> Iterable[type]:
    import app

    seen: set[type] = set()
    for mod_info in pkgutil.walk_packages(app.__path__, prefix="app."):
        try:
            mod = importlib.import_module(mod_info.name)
        except Exception:
            continue
        for _, obj in inspect.getmembers(mod):
            if (
                inspect.isclass(obj)
                and hasattr(obj, "__tablename__")
                and hasattr(obj, "__table__")
                and obj not in seen
            ):
                seen.add(obj)
                yield obj


def test_every_vector_table_is_classified():
    """Every table with a pgvector column is either per-user (has user_id)
    or in the GLOBAL_CATALOG_TABLES allowlist. New models that aren't both
    will fail this test until classified explicitly.
    """
    offenders: list[tuple[str, str]] = []
    classified: list[str] = []

    for cls in _all_model_classes():
        try:
            table = cls.__table__
        except Exception:
            continue
        cols = list(table.columns)
        if not _has_vector_column(cols):
            continue

        if table.name in GLOBAL_CATALOG_TABLES:
            classified.append(f"{table.name} (global)")
            continue
        if _has_user_id(cols):
            classified.append(f"{table.name} (per-user)")
            continue

        offenders.append((cls.__name__, table.name))

    assert not offenders, (
        f"pgvector tables not classified for tenancy: {offenders}. "
        f"Either add 'user_id' column (per-user) or add table name to "
        f"GLOBAL_CATALOG_TABLES. See docs/security/pgvector-tenancy.md."
    )
    # Sanity: at least the known vector tables were detected.
    assert any(
        "recipes" in c or "foods" in c for c in classified
    ), f"Expected to detect recipes/foods vector tables; got: {classified}"
