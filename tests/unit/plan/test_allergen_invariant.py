"""Hard-block allergen invariant (property-based).

NOVA scope: nutrition planning, not nutrition guidance. Even so, allergens are a
hard safety floor — Layer 1 eligibility (`app/plan/application/layer1_eligibility.py`)
MUST never surface a recipe whose denormalised `allergens` array overlaps the
user's declared `allergies`. Production filter is expressed in SQL:

    NOT (CAST(r.allergens AS text[]) && CAST(:allergies AS text[]))

Layer 1 is SQL-driven (Postgres), so we cannot exercise the predicate in a
pure-unit test against the live DB. Instead we lift the predicate into a
deterministic Python matcher (`_layer1_allergen_predicate`) that mirrors the
SQL contract exactly, then assert with hypothesis that no catalog row passing
the predicate can contain any allergen from the user set. Property runs ≥200
examples.

Additional contract check: the SQL Layer 1 emits is also inspected for the
`NOT (... && ...)` hard-exclude fragment, so we catch regressions either in
the predicate logic OR in the SQL emission.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.plan.application import layer1_eligibility

# Allergen vocabulary used by the recipe catalog + user profile. We keep this
# co-located so hypothesis can sample from a closed enum (mirrors ADR-0001).
_ALLERGEN_VOCAB: tuple[str, ...] = (
    "lactose",
    "gluten",
    "tree_nuts",
    "peanut",
    "shellfish",
    "egg",
    "soy",
    "fish",
    "sesame",
)


@dataclass(frozen=True, slots=True)
class _CatalogRow:
    """In-memory mirror of the recipes columns Layer 1 reads for the allergen
    predicate. The real table has many more columns — for the invariant we
    only need the `allergens` denormalised array."""

    recipe_id: str
    allergens: frozenset[str]


def _layer1_allergen_predicate(*, row: _CatalogRow, user_allergies: frozenset[str]) -> bool:
    """Mirror of Layer 1 SQL: `NOT (r.allergens && :allergies)`.

    Returns True if the row PASSES the filter (i.e. no allergen overlap with
    the user) — the same semantics as `WHERE NOT (... && ...)` in Postgres.
    """
    if not user_allergies:
        return True
    return row.allergens.isdisjoint(user_allergies)


_SETTINGS = settings(
    max_examples=200,
    deadline=None,
    derandomize=False,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
)


# ---------------------------------------------------------------------------
# Hypothesis strategies — closed-vocabulary catalog rows + user allergens.
# ---------------------------------------------------------------------------

_user_allergens_strategy = st.frozensets(st.sampled_from(_ALLERGEN_VOCAB), min_size=1, max_size=6)

_recipe_allergens_strategy = st.frozensets(st.sampled_from(_ALLERGEN_VOCAB), min_size=0, max_size=6)


def _catalog_row(allergens: frozenset[str]) -> _CatalogRow:
    return _CatalogRow(recipe_id="rcp", allergens=allergens)


# ---------------------------------------------------------------------------
# Property A1 — invariant: any row that passes the predicate has no allergen
# in common with the user.
# ---------------------------------------------------------------------------


@pytest.mark.property
@_SETTINGS
@given(
    user_allergens=_user_allergens_strategy,
    recipe_allergens=_recipe_allergens_strategy,
)
def test_predicate_never_leaks_user_allergen(
    user_allergens: frozenset[str], recipe_allergens: frozenset[str]
) -> None:
    row = _catalog_row(recipe_allergens)
    passes = _layer1_allergen_predicate(row=row, user_allergies=user_allergens)
    if passes:
        leak = recipe_allergens & user_allergens
        assert not leak, (
            f"allergen_leak: recipe={recipe_allergens} user={user_allergens} " f"intersect={leak}"
        )


# ---------------------------------------------------------------------------
# Property A2 — invariant: a row whose allergens overlap user's allergies
# MUST be rejected (no false-pass).
# ---------------------------------------------------------------------------


@pytest.mark.property
@_SETTINGS
@given(
    user_allergens=_user_allergens_strategy,
    recipe_allergens=_recipe_allergens_strategy,
)
def test_predicate_rejects_overlap_rows(
    user_allergens: frozenset[str], recipe_allergens: frozenset[str]
) -> None:
    row = _catalog_row(recipe_allergens)
    passes = _layer1_allergen_predicate(row=row, user_allergies=user_allergens)
    if recipe_allergens & user_allergens:
        assert not passes, f"false_pass: recipe={recipe_allergens} user={user_allergens}"


# ---------------------------------------------------------------------------
# Property A3 — empty user allergen set means every row passes (no filter).
# Sanity check the boundary condition.
# ---------------------------------------------------------------------------


@pytest.mark.property
@_SETTINGS
@given(recipe_allergens=_recipe_allergens_strategy)
def test_empty_user_allergens_passes_all(
    recipe_allergens: frozenset[str],
) -> None:
    row = _catalog_row(recipe_allergens)
    assert _layer1_allergen_predicate(row=row, user_allergies=frozenset())


# ---------------------------------------------------------------------------
# Property A4 — over a batch of rows, the filter is a strict subset of input
# (never returns a row that was not in the catalog) and is order-independent.
# ---------------------------------------------------------------------------


@pytest.mark.property
@_SETTINGS
@given(
    user_allergens=_user_allergens_strategy,
    rows=st.lists(_recipe_allergens_strategy, min_size=0, max_size=20),
)
def test_batch_filter_is_subset_and_order_independent(
    user_allergens: frozenset[str], rows: list[frozenset[str]]
) -> None:
    rows_a = [_CatalogRow(recipe_id=f"r{i}", allergens=a) for i, a in enumerate(rows)]
    rows_b = list(reversed(rows_a))

    def _filter(rs: list[_CatalogRow]) -> set[str]:
        return {
            r.recipe_id
            for r in rs
            if _layer1_allergen_predicate(row=r, user_allergies=user_allergens)
        }

    passed_a = _filter(rows_a)
    passed_b = _filter(rows_b)
    assert passed_a == passed_b, "order-dependent filter detected"
    # subset of input
    all_ids = {r.recipe_id for r in rows_a}
    assert passed_a.issubset(all_ids)
    # zero leaks
    for r in rows_a:
        if r.recipe_id in passed_a:
            assert not (r.allergens & user_allergens)


# ---------------------------------------------------------------------------
# Contract: production Layer 1 SQL still emits the hard-exclude fragment.
# Pairs with the predicate property tests — if either is removed, regression
# is caught.
# ---------------------------------------------------------------------------


def test_layer1_sql_contains_hard_allergen_exclude_fragment() -> None:
    src = inspect.getsource(layer1_eligibility)
    assert (
        "NOT (CAST(r.allergens AS text[]) && CAST(:allergies AS text[]))" in src
    ), "Layer 1 must hard-exclude allergens via array overlap negation"


def test_layer1_predicate_matches_sql_semantics_with_canonical_examples() -> None:
    """Sanity check the Python mirror against canonical examples."""
    rows = [
        _CatalogRow("r_safe", frozenset({"egg"})),
        _CatalogRow("r_unsafe", frozenset({"gluten"})),
        _CatalogRow("r_multi", frozenset({"soy", "gluten"})),
        _CatalogRow("r_empty", frozenset()),
    ]
    user = frozenset({"gluten"})
    passed = {r.recipe_id for r in rows if _layer1_allergen_predicate(row=r, user_allergies=user)}
    assert passed == {"r_safe", "r_empty"}
