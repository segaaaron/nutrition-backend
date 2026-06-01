"""ConditionGate Strategy invariants (H2.2–H2.6).

Covers the five new gates (PregnancyGate, DiabetesT2Gate, CKDGate,
HypertensionGate, CeliacGate). Each gate is a frozen dataclass that
contributes a parameterized SQL fragment to Layer 1 eligibility.

Invariants asserted:
- Auto-registration at import time (registry contains the gate instance).
- contribute_sql() returns non-empty SQL + dict of params.
- Every `:name` placeholder in SQL has a matching key in params and vice
  versa (no orphan params, no missing references).
- SQL fragment is parenthesised and contains no obvious injection.
- gate.condition is a member of CONDITIONS_25 and matches the module file.
- All registered gates hash stably (frozen dataclass guarantee).
- Layer 1 composition: for a frozenset of conditions, the *multiset* of
  contributed SQL fragments is invariant under set iteration order
  (composition is commutative — order of AND is irrelevant semantically).
"""
from __future__ import annotations

import re
from dataclasses import is_dataclass
from typing import Protocol, cast

from hypothesis import given, settings
from hypothesis import strategies as st

from app.plan.domain.condition_gates import (  # noqa: F401 — triggers registration
    CONDITION_GATES,
    CeliacGate,
    CKDGate,
    DiabetesT2Gate,
    HypertensionGate,
    LactationGate,
    PregnancyGate,
    gates_for,
)
from app.shared.domain.vocabularies import CONDITIONS_25

# Match `:name` SQLAlchemy bind params. Negative lookbehind excludes `::`
# (PostgreSQL typecast operator, e.g. `ARRAY['gluten']::text[]`).
_PLACEHOLDER_RE = re.compile(r"(?<!:):([a-zA-Z_][a-zA-Z0-9_]*)")


class _GateProto(Protocol):
    @property
    def condition(self) -> str: ...

    def contribute_sql(self) -> tuple[str, dict[str, object]]: ...


def _as_gate(g: object) -> _GateProto:
    """Narrow registry-returned `_GateLike` (the registry's minimal
    Protocol exposes only `.condition`) to the local Protocol that also
    declares `contribute_sql`. All registered gates implement both
    structurally; assert at runtime and cast for the type checker."""
    assert hasattr(g, "contribute_sql")
    return cast(_GateProto, g)


# ---------------------------------------------------------------------------
# Registration: PregnancyGate
# ---------------------------------------------------------------------------


def test_pregnancy_registered_at_import() -> None:
    gates = gates_for("pregnancy")
    assert any(isinstance(g, PregnancyGate) for g in gates)


def test_diabetes_t2_registered_at_import() -> None:
    gates = gates_for("diabetes_t2")
    assert any(isinstance(g, DiabetesT2Gate) for g in gates)


def test_ckd_registered_at_import() -> None:
    gates = gates_for("ckd")
    assert any(isinstance(g, CKDGate) for g in gates)


def test_hypertension_registered_at_import() -> None:
    gates = gates_for("hypertension")
    assert any(isinstance(g, HypertensionGate) for g in gates)


def test_celiac_registered_at_import() -> None:
    gates = gates_for("celiac")
    assert any(isinstance(g, CeliacGate) for g in gates)


# ---------------------------------------------------------------------------
# Per-gate property suite (parametrised over the 5 new gates).
# ---------------------------------------------------------------------------

_GATE_INSTANCES: list[_GateProto] = [
    PregnancyGate(),
    DiabetesT2Gate(),
    CKDGate(),
    HypertensionGate(),
    CeliacGate(),
]

_GATE_EXPECTED_CONDITION: dict[str, str] = {
    "PregnancyGate": "pregnancy",
    "DiabetesT2Gate": "diabetes_t2",
    "CKDGate": "ckd",
    "HypertensionGate": "hypertension",
    "CeliacGate": "celiac",
}


@settings(max_examples=200, deadline=None)
@given(idx=st.integers(min_value=0, max_value=len(_GATE_INSTANCES) - 1))
def test_gate_contributes_non_empty_sql(idx: int) -> None:
    gate = _GATE_INSTANCES[idx]
    sql, params = gate.contribute_sql()
    assert isinstance(sql, str)
    assert len(sql) > 0
    assert isinstance(params, dict)


@settings(max_examples=200, deadline=None)
@given(idx=st.integers(min_value=0, max_value=len(_GATE_INSTANCES) - 1))
def test_gate_params_referenced_in_sql(idx: int) -> None:
    """Every params key appears as `:key` in SQL; every `:key` in SQL has
    a matching params entry (no orphans either direction). Special case:
    CeliacGate has zero params and zero placeholders."""
    gate = _GATE_INSTANCES[idx]
    sql, params = gate.contribute_sql()
    placeholders = set(_PLACEHOLDER_RE.findall(sql))
    keys = set(params.keys())
    assert keys == placeholders, (
        f"{gate.__class__.__name__}: params {keys} != placeholders {placeholders}"
    )


@settings(max_examples=200, deadline=None)
@given(idx=st.integers(min_value=0, max_value=len(_GATE_INSTANCES) - 1))
def test_gate_sql_is_safe_fragment(idx: int) -> None:
    """SQL fragment must be parenthesised + free of obvious injection.

    Layer 1 ANDs the fragment into a larger WHERE clause; an unparenthesised
    fragment with a top-level OR would mis-bind. We also reject unsafe
    constructs that hint at injection (semicolons, comment markers, drop).
    """
    gate = _GATE_INSTANCES[idx]
    sql, _ = gate.contribute_sql()
    assert sql.startswith("(") and sql.endswith(")"), (
        f"{gate.__class__.__name__} SQL not parenthesised: {sql!r}"
    )
    lowered = sql.lower()
    assert ";" not in sql
    assert "--" not in sql
    assert "/*" not in sql and "*/" not in sql
    assert "drop " not in lowered
    assert "delete " not in lowered
    assert "insert " not in lowered
    assert "update " not in lowered


@settings(max_examples=200, deadline=None)
@given(idx=st.integers(min_value=0, max_value=len(_GATE_INSTANCES) - 1))
def test_gate_condition_matches_vocabulary(idx: int) -> None:
    gate = _GATE_INSTANCES[idx]
    expected = _GATE_EXPECTED_CONDITION[gate.__class__.__name__]
    assert gate.condition == expected
    assert gate.condition in CONDITIONS_25


# ---------------------------------------------------------------------------
# Cross-cutting properties.
# ---------------------------------------------------------------------------


def test_all_registered_gates_are_frozen_dataclasses() -> None:
    """Frozen dataclass guarantees hashability + structural identity,
    enabling registry caching and stable Layer 1 composition keys."""
    for gates in CONDITION_GATES.values():
        for gate in gates:
            assert is_dataclass(gate), f"{gate!r} not a dataclass"
            # Frozen instances support hash() — call it to assert.
            hash(gate)


@settings(max_examples=200, deadline=None)
@given(
    conds=st.lists(
        st.sampled_from(["lactation", "pregnancy", "ckd", "hypertension",
                         "diabetes_t2", "celiac"]),
        min_size=1, max_size=4, unique=True,
    ),
)
def test_layer1_dispatch_multiset_invariant(conds: list[str]) -> None:
    """For a frozenset of conditions, the *multiset* of contributed SQL
    fragments is invariant under iteration order.

    Layer 1 iterates `for cond in conditions` over a set — iteration order
    is implementation-defined. AND is commutative, so the semantic filter
    is order-independent. We assert that the SORTED list of SQL fragments
    is the same for forward and reverse iteration.
    """
    forward = []
    for c in conds:
        for g in gates_for(c):
            sql, _ = _as_gate(g).contribute_sql()
            forward.append(sql)
    reverse = []
    for c in reversed(conds):
        for g in gates_for(c):
            sql, _ = _as_gate(g).contribute_sql()
            reverse.append(sql)
    assert sorted(forward) == sorted(reverse)


@settings(max_examples=200, deadline=None)
@given(
    conds=st.lists(
        st.sampled_from(["lactation", "pregnancy", "ckd", "hypertension",
                         "diabetes_t2", "celiac"]),
        min_size=1, max_size=4, unique=True,
    ),
)
def test_layer1_dispatch_params_no_collision(conds: list[str]) -> None:
    """Every gate uses a unique parameter-name prefix (lac_, preg_, dt2_,
    ckd_, ht_, celiac has none). When Layer 1 merges params via dict.update
    across multiple gates for a multi-condition user, no key should collide."""
    seen: set[str] = set()
    for c in conds:
        for g in gates_for(c):
            _, p = _as_gate(g).contribute_sql()
            for k in p:
                assert k not in seen, f"param collision: {k} in {conds}"
                seen.add(k)
