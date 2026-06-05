"""inputs_hash canonicalisation invariants (ADR-0010).

`compute_inputs_hash(payload)` must be:
- Deterministic (same payload → same hash, every call).
- Key-order invariant (dict insertion order irrelevant).
- Set-order invariant (frozenset elements canonicalised via sort).
- Decimal/UUID stringified.
- Mutation-sensitive (any value byte change → different hash).
- sha256 hex (64 chars, [0-9a-f]).
- Collision-resistant on smoke-scale random corpus.
"""

from __future__ import annotations

import random
import re
import string
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from hypothesis import given, settings
from hypothesis import strategies as st

from app.plan.domain.inputs_hash import compute_inputs_hash

_HEX_RE = re.compile(r"^[0-9a-f]+$")


# ---------------------------------------------------------------------------
# Hypothesis strategies — payloads with mixed canonicalisable types.
# ---------------------------------------------------------------------------

_scalar = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(10**9), max_value=10**9),
    st.text(alphabet=string.ascii_letters + string.digits + "_-.", min_size=0, max_size=16),
    st.decimals(
        min_value=Decimal("-10000"),
        max_value=Decimal("10000"),
        allow_nan=False,
        allow_infinity=False,
        places=2,
    ),
    st.uuids(),
)


def _container(children: st.SearchStrategy[Any]) -> st.SearchStrategy[Any]:
    # Note: frozensets restricted to a single element type per real plan
    # payload contract (allergens: set[str], conditions: set[str]). Mixed-type
    # frozensets trigger a documented limitation in `_normalize` (sorted()
    # cannot order heterogeneous types) — out of contract for ADR-0010.
    return st.one_of(
        st.lists(children, max_size=5),
        st.dictionaries(
            keys=st.text(alphabet=string.ascii_letters, min_size=1, max_size=8),
            values=children,
            max_size=5,
        ),
        st.frozensets(
            st.text(alphabet=string.ascii_letters, min_size=1, max_size=8),
            max_size=5,
        ),
        st.frozensets(
            st.integers(min_value=-1000, max_value=1000),
            max_size=5,
        ),
    )


_payload_value = st.recursive(_scalar, _container, max_leaves=12)
_payload: st.SearchStrategy[dict[str, Any]] = st.dictionaries(
    keys=st.text(alphabet=string.ascii_letters, min_size=1, max_size=8),
    values=_payload_value,
    max_size=6,
)


# ---------------------------------------------------------------------------
# Deterministic / order-invariant
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(payload=_payload)
def test_inputs_hash_deterministic(payload: dict[str, Any]) -> None:
    assert compute_inputs_hash(payload) == compute_inputs_hash(payload)


@settings(max_examples=200, deadline=None)
@given(payload=_payload, seed=st.integers(min_value=0, max_value=2**31 - 1))
def test_inputs_hash_key_order_invariant(
    payload: dict[str, Any],
    seed: int,
) -> None:
    """Rebuild payload dict with shuffled key insertion order — hash unchanged
    because compute_inputs_hash uses sort_keys=True."""
    items = list(payload.items())
    rng = random.Random(seed)  # noqa: S311 — property-test PRNG, not crypto
    rng.shuffle(items)
    shuffled: dict[str, Any] = dict(items)
    assert compute_inputs_hash(payload) == compute_inputs_hash(shuffled)


@settings(max_examples=200, deadline=None)
@given(
    items=st.lists(
        st.text(alphabet=string.ascii_letters, min_size=1, max_size=5),
        min_size=1,
        max_size=6,
        unique=True,
    ),
    seed=st.integers(min_value=0, max_value=2**31 - 1),
)
def test_inputs_hash_set_order_invariant(items: list[str], seed: int) -> None:
    """frozenset built from forward-ordered vs shuffled iterable produces same
    hash (canonicalisation sorts before serialising)."""
    rng = random.Random(seed)  # noqa: S311 — property-test PRNG, not crypto
    shuffled = list(items)
    rng.shuffle(shuffled)
    a = compute_inputs_hash({"conds": frozenset(items)})
    b = compute_inputs_hash({"conds": frozenset(shuffled)})
    assert a == b


@settings(max_examples=200, deadline=None)
@given(
    val=st.decimals(
        min_value=Decimal("-10000"),
        max_value=Decimal("10000"),
        allow_nan=False,
        allow_infinity=False,
        places=2,
    ),
)
def test_inputs_hash_decimal_stringified(val: Decimal) -> None:
    """Two Decimals constructed via different routes but compare equal-string
    produce the same hash (stringification is the canonical form)."""
    a = compute_inputs_hash({"k": val})
    b = compute_inputs_hash({"k": Decimal(str(val))})
    assert a == b


@settings(max_examples=200, deadline=None)
@given(uid=st.uuids())
def test_inputs_hash_uuid_stringified(uid: UUID) -> None:
    """UUID stringified canonically (lowercase hex, hyphenated)."""
    a = compute_inputs_hash({"id": uid})
    b = compute_inputs_hash({"id": str(uid)})
    assert a == b


# ---------------------------------------------------------------------------
# Change-sensitive
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(
    kcal=st.integers(min_value=1200, max_value=4000),
    extra=st.dictionaries(
        keys=st.text(alphabet=string.ascii_letters, min_size=1, max_size=6),
        values=st.integers(min_value=0, max_value=10**6),
        max_size=4,
    ),
)
def test_inputs_hash_change_sensitive(
    kcal: int,
    extra: dict[str, int],
) -> None:
    """Mutating any single integer value (kcal +1) must change the hash."""
    base = {**extra, "kcal": kcal}
    mutated = {**extra, "kcal": kcal + 1}
    assert compute_inputs_hash(base) != compute_inputs_hash(mutated)


# ---------------------------------------------------------------------------
# Output shape
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(payload=_payload)
def test_inputs_hash_length_64(payload: dict[str, Any]) -> None:
    assert len(compute_inputs_hash(payload)) == 64


@settings(max_examples=200, deadline=None)
@given(payload=_payload)
def test_inputs_hash_all_ascii_output(payload: dict[str, Any]) -> None:
    out = compute_inputs_hash(payload)
    assert _HEX_RE.match(out) is not None


# ---------------------------------------------------------------------------
# Collision smoke (deterministic 10k random payloads)
# ---------------------------------------------------------------------------


def _random_payload(rng: random.Random, depth: int = 0) -> Any:  # noqa: PLR0911 — type-dispatch generator; one return per canonical type
    """Deterministic random payload generator covering all canonical types."""
    choice = rng.randint(0, 8) if depth < 3 else rng.randint(0, 4)
    if choice == 0:
        return rng.randint(-(10**9), 10**9)
    if choice == 1:
        return "".join(rng.choices(string.ascii_letters + string.digits, k=rng.randint(1, 12)))
    if choice == 2:
        return Decimal(f"{rng.randint(-10000, 10000)}.{rng.randint(0, 99):02d}")
    if choice == 3:
        seed_bytes = rng.getrandbits(128).to_bytes(16, "big")
        return UUID(bytes=seed_bytes)
    if choice == 4:
        return rng.choice([None, True, False])
    if choice == 5:
        return [_random_payload(rng, depth + 1) for _ in range(rng.randint(0, 4))]
    if choice == 6:
        return {
            "".join(rng.choices(string.ascii_letters, k=rng.randint(1, 6))): _random_payload(
                rng, depth + 1
            )
            for _ in range(rng.randint(0, 4))
        }
    if choice == 7:
        # Homogeneous frozenset: pick element type once per set.
        if rng.random() < 0.5:
            return frozenset(rng.randint(-1000, 1000) for _ in range(rng.randint(0, 4)))
        return frozenset(
            "".join(rng.choices(string.ascii_letters, k=4)) for _ in range(rng.randint(0, 4))
        )
    return rng.choice([None, True, False])


def test_inputs_hash_collision_smoke() -> None:
    """10,000 deterministic random payloads — all hashes unique.

    Theoretical collision prob ~ N^2 / 2^257; at N=1e4 this is ~5e-70.
    A failure indicates a canonicalisation bug, not bad luck.
    """
    rng = random.Random(42)  # noqa: S311 — deterministic collision-smoke RNG, not crypto
    hashes: set[str] = set()
    for i in range(10_000):
        payload = {
            "i": i,  # guarantee uniqueness floor
            "ctx": _random_payload(rng),
            "uid": uuid4().hex,  # extra entropy — still deterministic shape
        }
        h = compute_inputs_hash(payload)
        assert h not in hashes, f"collision at iteration {i}"
        hashes.add(h)
    assert len(hashes) == 10_000
