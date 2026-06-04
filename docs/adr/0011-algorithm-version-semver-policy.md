# ADR-0011 — `algorithm_version` semver bump policy

**Status:** Accepted
**Date:** 2026-06-01
**Context:** Migration 0009 introduced `plan_versions.algorithm_version TEXT NOT NULL`. Master plan H1 ships with `"0.1.0"`. This ADR defines when and how the version bumps so plan history remains auditable across algorithm evolution.

## Semver mapping for plan algorithm

| Component | Semantic | Triggers |
|-----------|----------|----------|
| **MAJOR** | Breaking response shape OR breaking invariant | New required field on plan output; removal of a field mobile clients consume; invariant change (e.g., MACRO_TOLERANCE changes from 2% to 1%); user-visible kcal target methodology change (e.g., Mifflin → Harris-Benedict default) |
| **MINOR** | Additive capability | New `ConditionGate` registered (e.g., `pregnancy`); new `RankingSignal` (e.g., `MicronutrientBioavailability`); new pipeline `Stage`; new optional response field; new variant promoted to baseline in `plan_weight_vectors`; algorithm gains a new safe state (e.g., recalibration saga reaches new step) |
| **PATCH** | Bug fix or weight tune | Weight vector adjustment within existing variant; bug fix that nudges outputs by ≤2%; documentation; performance optimization without behavior change |

## Decision rules

### When in doubt, bump major.

The algorithm is the product moat. Auditors + nutrition reviewers must be able to attribute outcomes to a specific version. A wrong-bump-down (patch instead of major) silently merges incomparable cohorts in analytics.

### Version is owned by code

Centralised at `app/plan/domain/algorithm_version.py`:

```python
from __future__ import annotations
from typing import Final
ALGORITHM_VERSION: Final[str] = "0.1.0"
```

Every plan generation reads this constant. CI test asserts the constant changes whenever the file diff in `app/plan/` is non-trivial (`ruff` custom rule deferred; for now: code-review checklist item).

### Version is monotonic per environment

Never reuse a version. If staging shipped 0.2.0 and prod is still on 0.1.5, prod path is 0.1.5 → 0.2.0 (skip 0.1.6+). Never publish 0.2.0 with different code in two environments.

### Major bump triggers parallel ramp

- New major version ships under variant_id `<major>.<minor>.<patch>` first.
- Old major remains the baseline.
- A/B over 14 days minimum; success criteria pre-registered.
- Switch baseline only after pre-registered criteria met.
- Old version remains queryable via `plan_versions.algorithm_version` indefinitely.

## Examples

| Change | Bump | Rationale |
|--------|------|-----------|
| Add `JaccardVarietyPenalty` to ranking signals | 0.1.0 → **0.2.0** | New `RankingSignal` registered |
| Switch L1 BMR from Mifflin to Cunningham for athletes | 0.1.0 → **0.2.0** | New safe pathway, not breaking (existing users unaffected) |
| Lower MACRO_TOLERANCE from Decimal("0.02") to Decimal("0.01") | 0.1.0 → **1.0.0** | Invariant tightening; old plans may not satisfy new tolerance, breaking audit consistency |
| Add `MicronutrientBioavailability` signal | 0.2.0 → **0.3.0** | New signal, additive |
| Promote variant `v0.3.0_kcal_fit_+5` to baseline | 0.3.0 → **0.4.0** | Baseline weights change, downstream behavior shifts |
| Fix off-by-one in Layer1 GI gate | 0.4.0 → **0.4.1** | Bug fix, behavior delta <2% |
| Remove deprecated `compute_water_ml` from response | 0.4.1 → **1.0.0** | Field removal, mobile contract break |
| Add `pregnancy_safe` filter to L1 (new condition unlock) | 1.0.0 → **1.1.0** | New gate, additive |

## Telemetry

- `plan_versions.algorithm_version` GROUP BY for cohort analysis.
- Prometheus label `algorithm_version` on `plan_generation_seconds` histogram.
- Weekly rollup: distribution of versions in active plans + median age per version.

## Deprecation

When promoting a new major:

1. Tag old major as deprecated in `app/plan/domain/algorithm_version.py` with `DEPRECATED_VERSIONS: frozenset[str]`.
2. API responses for deprecated-version plans include `Deprecation: true` header + `Sunset` per RFC 8594.
3. After 90d sunset, force regenerate on next user activity (auto-bump, push notify).
4. Deprecated plan rows stay in `plan_versions` forever (immutable audit).

## Consequences

### Positive

- Auditors can pinpoint exactly which algorithm produced a plan, regardless of catalog drift.
- A/B is structurally safe: variant_id + algorithm_version together identify the experiment cell.
- Mobile clients can refuse-render or downgrade-render plans whose version > supported.

### Negative

- Version bump discipline costs developer time. Mitigation: PR template checkbox; code review checklist.

### Risks

- Forgotten bump on a behavior change → silent cohort blending in analytics. Mitigation: CI gate on diff size in `app/plan/application/` + `app/plan/domain/` forcing PR author to declare bump category.

## References

- ADR-0009 Decimal-strict migration (algorithm_version was introduced alongside)
- ADR-0010 inputs_hash (algorithm_version is part of the payload)
- Migration 0009 `plan_versions.algorithm_version`
- Master plan `docs/algorithms/MASTER_PLAN_ALGORITHM.md` — three-horizon roadmap drives the bump sequence
