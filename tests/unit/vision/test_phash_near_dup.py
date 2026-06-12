"""pHash near-duplicate dedup invariants (cost lever 2026-06-11).

libvips is absent in this environment, so `compute_phash_64` is exercised
only for its graceful-degradation contract (None, never raise); the
Hamming/lookup logic is tested with synthetic hashes.
"""

from __future__ import annotations

from app.imaging.infrastructure.phash import (
    HAMMING_NEAR_DUP,
    compute_phash_64,
    hamming,
)


def test_compute_phash_degrades_to_none_without_libvips_or_bad_bytes() -> None:
    # Must NEVER raise: pHash is an optimization, not a dependency.
    assert compute_phash_64(b"not an image at all") is None


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
