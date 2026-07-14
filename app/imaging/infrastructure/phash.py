"""Perceptual hash (aHash 8×8) for near-duplicate photo detection.

Cost-reduction lever (2026-06-11): the SHA-256 dedup cache only catches
byte-identical re-uploads. The far more common real pattern — user
re-photographs the same plate seconds later (blur retry, second angle),
or photographs an identical daily breakfast — produces different bytes
every time and pays a full OpenAI vision call. An 8×8 average-hash over
the greyscale thumbnail catches those for ~0 cost.

Implementation notes:
- pyvips imported lazily: libvips ships in the worker container but not
  in every dev/test environment. `compute_phash_64` degrades to None on
  any failure — pHash is an optimization, never a dependency.
- The hash is masked to 63 bits so it always fits a SIGNED Postgres
  BIGINT (`vision_jobs.phash_64`, migration 0013). Losing the top bit
  costs nothing measurable for near-dup detection, and it keeps XOR/
  popcount arithmetic correct everywhere (including the anomaly signal
  `worker/anomaly_signals/phash_clustering.py`, which reads this column
  and was waiting for a producer since 0013 shipped).
- aHash (mean threshold) over an 8×8 luma thumbnail. Hamming distance
  ≤ HAMMING_NEAR_DUP on 63 bits ≈ same scene; threshold matches the
  anomaly signal's clustering threshold.
"""

from __future__ import annotations

from app.core.logging import get_logger

log = get_logger("imaging.phash")

_MASK_63 = (1 << 63) - 1

# Same-scene threshold (inclusive): d ≤ 4 ⇒ near-dup. Matches the anomaly
# signal's exclusive `d < 5` (phash_clustering._HAMMING_THRESHOLD = 5).
HAMMING_NEAR_DUP = 4


def compute_phash_64(image_bytes: bytes) -> int | None:
    """8×8 average-hash of the image luma, masked to 63 bits.

    Returns None when libvips is unavailable or the image cannot be
    decoded — callers treat None as "no pHash, proceed without dedup".
    """
    try:
        import pyvips  # noqa: PLC0415 — lazy: libvips absent in some envs

        img = pyvips.Image.thumbnail_buffer(
            image_bytes, 8, height=8, size="force"
        ).colourspace("b-w")
        # 8×8 single-band uchar buffer → 64 luma samples. write_to_memory()
        # returns a pyvips buffer whose iteration yields length-1 `bytes`
        # (b'L'), not ints — wrap in bytes() so list() yields 0-255 ints and
        # sum()/comparison work. Without this every hash raised TypeError and
        # the near-dup cache silently never fired.
        pixels = list(bytes(img.write_to_memory()))[:64]
        if len(pixels) < 64:
            return None
        mean = sum(pixels) / 64.0
        bits = 0
        for p in pixels:
            bits = (bits << 1) | (1 if p >= mean else 0)
        return bits & _MASK_63
    except Exception as exc:  # noqa: BLE001 — OK4: best-effort optimization; decode/lib failure must never break the photo pipeline
        log.debug("phash.compute_failed", error=str(exc))
        return None


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()
