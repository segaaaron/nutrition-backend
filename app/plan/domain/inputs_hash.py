"""Plan inputs_hash canonical form (ADR-0010).

`compute_inputs_hash(payload)` returns the sha256 hex of a canonically
serialized payload dict. Used by `plan_versions.inputs_hash` for audit
fingerprinting and `Idempotency-Key` plan-gen dedupe.

Canonicalization rules (ADR-0010):
1. Decimals stringified via `str(value)` after quantize.
2. UUIDs lowercased hex with hyphens (Python default).
3. Sets materialized as sorted lists (ASCII order).
4. Missing values → `null` (never omit keys).
5. JSON dumped with sort_keys=True + separators=(",", ":") + ensure_ascii=True.
6. SHA-256 hex of UTF-8 / ASCII bytes.

Deterministic across processes / Python versions / machine endianness.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any
from uuid import UUID


def _normalize(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, set | frozenset):
        return sorted(_normalize(x) for x in obj)
    if isinstance(obj, dict):
        return {k: _normalize(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_normalize(x) for x in obj]
    return obj


def compute_inputs_hash(payload: dict[str, Any]) -> str:
    """Return canonical sha256 hex of payload. ADR-0010 contract."""
    canonical = json.dumps(
        _normalize(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()
