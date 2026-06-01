"""Algorithm version constant — single source of truth (ADR-0011).

Every plan generation reads `ALGORITHM_VERSION` and persists it on
`plan_versions.algorithm_version`. Mobile clients receive it in the plan
response payload.

Bump policy (ADR-0011):
- MAJOR: breaking response shape OR breaking invariant (MACRO_TOLERANCE change,
  formula switch with user-visible kcal shift).
- MINOR: additive capability (new ConditionGate, new RankingSignal, new Stage,
  new optional response field, new variant promoted to baseline).
- PATCH: bug fix or weight tune (delta ≤2% on outputs).

Current line:
- 0.1.0 — H1 foundation shipped (Decimal-strict BMR/TDEE/macros, pipeline,
          ports, lactation Strategy registered).
"""
from __future__ import annotations

from typing import Final

ALGORITHM_VERSION: Final[str] = "0.1.0"

# Versions deprecated; mobile clients on these versions get `Deprecation: true`
# header + `Sunset` per RFC 8594. After sunset, force-regenerate on next user
# activity. Stored plans on deprecated versions remain queryable forever for
# audit (plan_versions table is immutable).
DEPRECATED_VERSIONS: Final[frozenset[str]] = frozenset()
