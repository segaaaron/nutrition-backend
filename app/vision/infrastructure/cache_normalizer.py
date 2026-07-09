"""Infrastructure — normalise raw repo cache-hit returns.

Single responsibility: one pure function that collapses the two legacy
return shapes (bare list, tuple-of-2) into a single canonical form so
callers don't need to branch on the shape.

Extracted from process_vision_job._normalize_cache_result so that
inflight_lock can reuse it without creating an application→application
circular import.
"""
from __future__ import annotations

from app.vision.domain.entities import DetectedFoodItem


def normalize_cache_result(
    result: object,
) -> tuple[list[DetectedFoodItem], str | None] | None:
    """Return ``(items, prompt_sha)`` or ``None`` for a cache miss.

    Handles three shapes emitted by repo doubles in tests:
      - ``None``                  → cache miss
      - ``(items, sha_str)``      → modern repo return
      - ``[item, ...]``           → legacy bare-list repo double
    """
    if result is None:
        return None
    if isinstance(result, tuple) and len(result) == 2:
        items_raw, sha_raw = result
        return list(items_raw), sha_raw if isinstance(sha_raw, str) else None
    if isinstance(result, list):
        return list(result), None
    return None
