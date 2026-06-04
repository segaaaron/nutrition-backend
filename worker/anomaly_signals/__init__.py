"""ADR-0026 L2 anomaly signals (pure async functions).

Each module exposes ``compute(session, user_id, window_days) -> SignalResult``
where ``SignalResult`` is either a finite float in ``[0, 100]`` or ``None`` to
indicate that the signal could not be computed (insufficient data, missing
backing infrastructure, etc.). The orchestrator in
``worker.anomaly_score_task`` redistributes weight across the *available*
signals when some return ``None`` (rule H of the implementation spec).
"""

from __future__ import annotations

SignalResult = float | None

__all__ = ["SignalResult"]
