"""pHash near-duplicate dedup invariants (cost lever 2026-06-11).

libvips is absent in this environment, so `compute_phash_64` is exercised
only for its graceful-degradation contract (None, never raise); the
Hamming/lookup logic is tested with synthetic hashes.
"""

from __future__ import annotations

import sys
import types

import pytest

from app.imaging.infrastructure.phash import (
    HAMMING_NEAR_DUP,
    compute_phash_64,
    hamming,
)


def test_compute_phash_degrades_to_none_without_libvips_or_bad_bytes() -> None:
    # Must NEVER raise: pHash is an optimization, not a dependency.
    assert compute_phash_64(b"not an image at all") is None


def test_compute_phash_handles_pyvips_byte_buffer(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression (2026-07-14): pyvips ``write_to_memory()`` returns a buffer
    whose ITERATION yields length-1 ``bytes`` (b'L'), not ints — so the old
    ``list(buf)`` produced ``[b'L', ...]`` and ``sum()`` raised ``TypeError``,
    which the broad-except swallowed. Result: EVERY hash silently returned
    None and the near-dup cache never fired. compute_phash_64 must produce a
    valid 63-bit int from such a buffer (the fix wraps it in ``bytes()``)."""

    class _FakeBuffer:
        def __init__(self, data: bytes) -> None:
            self._d = data

        def __iter__(self):  # yields bytes, exactly like the real pyvips buffer
            return (bytes([x]) for x in self._d)

        def __bytes__(self) -> bytes:
            return self._d

    class _FakeImg:
        def colourspace(self, _mode: str) -> _FakeImg:
            return self

        def write_to_memory(self) -> _FakeBuffer:
            return _FakeBuffer(bytes(range(64)))

    fake_pyvips = types.SimpleNamespace(
        Image=types.SimpleNamespace(thumbnail_buffer=lambda *a, **k: _FakeImg())
    )
    monkeypatch.setitem(sys.modules, "pyvips", fake_pyvips)

    h = compute_phash_64(b"whatever-bytes")
    assert isinstance(h, int), "hash must be produced, not swallowed to None"
    assert 0 <= h <= (1 << 63) - 1


def test_hamming_identical_is_zero() -> None:
    h = 0b1011_0010_1110_0001
    assert hamming(h, h) == 0


def test_hamming_counts_flipped_bits() -> None:
    a = 0b1111_0000
    b = 0b1010_0000
    assert hamming(a, b) == 2


def test_near_dup_threshold_separates_same_scene_from_different() -> None:
    base = int("1010110011010101" * 4, 2) & ((1 << 63) - 1)
    # 3 bit flips → same scene (≤ threshold)
    near = base ^ 0b10110
    assert hamming(base, near) <= HAMMING_NEAR_DUP
    # 20 bit flips → different plate
    far = base ^ int("1" * 20, 2)
    assert hamming(base, far) > HAMMING_NEAR_DUP


def test_phash_fits_signed_bigint() -> None:
    # 63-bit mask: any produced hash must fit Postgres signed BIGINT.
    max_63 = (1 << 63) - 1
    assert max_63 <= 2**63 - 1
    # The mask in compute_phash_64 guarantees this bound; verify the
    # constant relationship the storage contract relies on.
    from app.imaging.infrastructure.phash import _MASK_63

    assert _MASK_63 == max_63
