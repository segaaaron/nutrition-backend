# ADR-0010 — Plan inputs_hash canonical form

**Status:** Accepted
**Date:** 2026-06-01
**Context:** Migration 0009 introduced `plan_versions.inputs_hash TEXT NOT NULL`. The field is the audit fingerprint of every plan generation. This ADR defines its canonical form so producers + verifiers agree.

## Decision

`inputs_hash = sha256(canonical_json(payload)).hexdigest()` where `payload` is a Python dict serialized via `json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)`.

`payload` schema (all keys present, missing values as `null`):

```json
{
  "user_id": "<uuid>",
  "targets": {
    "kcal": "<decimal-string>",
    "protein_g": "<decimal-string>",
    "carbs_g": "<decimal-string>",
    "fat_g": "<decimal-string>",
    "fiber_g_min": "<decimal-string>",
    "meals_per_day": <int>
  },
  "conditions": ["<sorted_alphabetical>", ...],
  "allergens": ["<sorted_alphabetical>", ...],
  "region": "<5-char>",
  "meal_times": ["<sorted_alphabetical>", ...],
  "catalog_version": "<semver>",
  "taste_vector_version": <int>,
  "embedding_version": <int>,
  "algorithm_version": "<semver>",
  "variant_id": "<string>",
  "weights_checksum": "<sha256-hex>",
  "seed": <int>
}
```

### Canonicalization rules

1. **Decimals** stringified via `str(Decimal_value)` — preserves precision + scale. Examples: `"2056.00"`, `"103"`, `"0.02"`.
2. **UUIDs** stringified lowercase hex with hyphens (Python `str(UUID)` default).
3. **Sets** materialised as **sorted lists** (Python `sorted(...)` ASCII order).
4. **Missing values** → `null`. Never omit a key.
5. **JSON** dumped with `sort_keys=True`, `separators=(",", ":")` (no whitespace).
6. **Encoding** ASCII-only; non-ASCII region/meal_time/condition tokens are forbidden (ADR-0001 enforces).

### Producers

- `app/plan/application/create_plan.py` (Track C, when wired) — computes `inputs_hash` before persisting `plan_versions` row.
- `app/plan/application/recalibration_saga.py` (future) — same.
- Helper to ship: `app/plan/domain/inputs_hash.py` → `def compute_inputs_hash(payload: dict[str, object]) -> str`.

### Verifiers / consumers

- Compliance audit: replay `compute_inputs_hash(payload)` against stored value to detect tamper.
- Idempotency layer: identical `inputs_hash` within 1 hour → return cached `plan_version_id`.
- A/B telemetry: group plan outcomes by `(inputs_hash_prefix_8, variant_id)`.

## Consequences

### Positive

- Deterministic: same inputs → same hash, across processes + Python versions + machine endianness (SHA-256 + sorted-JSON is portable).
- Audit-strong: any change in any field flips the hash; tamper detection trivial.
- Idempotency-ready: enables `Idempotency-Key` semantics on `POST /v1/plan/generate`.
- A/B-ready: hash-prefix bucketing is uniform.

### Negative

- Decimal stringification couples on stored scale. Mitigation: always quantize Decimals to fixed scale before hashing (`quantize(Decimal("0.01"))` for kcal/macros, `quantize(Decimal("1"))` for grams). Helper enforces.

### Risks

- Future schema additions silently change hash for old plans. Mitigation: bump `algorithm_version` minor when payload schema changes; document the schema diff in the ADR amendment; never retro-rehash stored plans.

## Implementation

Helper module to be created during Track C wiring:

```python
# app/plan/domain/inputs_hash.py
from __future__ import annotations
import hashlib
import json
from decimal import Decimal
from typing import Any

def _normalize(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, (set, frozenset)):
        return sorted(_normalize(x) for x in obj)
    if isinstance(obj, dict):
        return {k: _normalize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_normalize(x) for x in obj]
    return obj

def compute_inputs_hash(payload: dict[str, object]) -> str:
    canonical = json.dumps(
        _normalize(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()
```

Property test (`tests/plan/property/test_inputs_hash.py` — owner task):
- Determinism: 1000 randomized payloads, hash same across reorderings of dict keys + set insertion order.
- Collision resistance smoke: 10k random payloads → no collision.

## Alternatives considered

1. **MD5** — rejected: weak; not for clinical-grade audit.
2. **BLAKE3** — rejected: extra dep; SHA-256 is stdlib + good enough at our scale.
3. **MessagePack canonical** — rejected: harder to debug; JSON sorts naturally; clear-text payload preserves grep-ability in incidents.
4. **Field hashing per category** — rejected: master plan needs one fingerprint, not five.

## References

- ADR-0001 closed vocabularies (constrains payload values to ASCII)
- ADR-0009 Decimal-strict migration (constrains Decimal stringification)
- Migration 0009 `plan_versions.inputs_hash`
