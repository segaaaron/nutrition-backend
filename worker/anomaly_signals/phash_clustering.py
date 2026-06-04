"""Signal: pHash duplicate clustering on vision_jobs.phash_64.

Counts photos within the user's window whose 64-bit perceptual hash has
Hamming distance ``< 5`` to at least one other photo from the same user.
Heavy clustering (the same plate uploaded repeatedly) is the canonical
photo-farming signature.

The migration 0013 added ``vision_jobs.phash_64 BIGINT NULL`` but the
vision worker is not yet computing it. When all rows in the window are
``NULL`` we return ``None`` so the orchestrator redistributes the 25 %
weight to other available signals.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from worker.anomaly_signals import SignalResult

_HAMMING_THRESHOLD = 5
_SCORE_PER_DUPLICATE = 10.0

_SQL = text(
    """
    SELECT phash_64
      FROM vision_jobs
     WHERE user_id = :uid
       AND created_at >= now() - (:days || ' days')::interval
       AND phash_64 IS NOT NULL
    """
)


def _hamming(a: int, b: int) -> int:
    # 64-bit XOR then popcount. Python ints are arbitrary precision; phash_64
    # is bounded so this stays O(1) per pair.
    return (a ^ b).bit_count()


def _cluster_count(hashes: list[int]) -> int:
    """Number of hashes that have at least one near-neighbour (d < 5).

    O(n^2) is fine: per-user windows cap in the low hundreds even for
    power users.
    """
    n = len(hashes)
    if n < 2:
        return 0
    matched: set[int] = set()
    for i in range(n):
        if i in matched:
            continue
        for j in range(i + 1, n):
            if _hamming(hashes[i], hashes[j]) < _HAMMING_THRESHOLD:
                matched.add(i)
                matched.add(j)
    return len(matched)


async def compute(
    session: AsyncSession, user_id: UUID, window_days: int
) -> SignalResult:
    rows = (
        await session.execute(_SQL, {"uid": str(user_id), "days": window_days})
    ).all()
    if not rows:
        return None
    hashes = [int(r[0]) for r in rows]
    count = _cluster_count(hashes)
    return min(100.0, count * _SCORE_PER_DUPLICATE)
