"""R2 — self-report intake bias correction.

Self-reported food intake systematically under-estimates true energy intake.
The bias is BMI-dependent: heavier subjects under-report more.

Sources:
- Lichtman SW, Pisarska K, Berman ER, et al. "Discrepancy between self-
  reported and actual caloric intake and exercise in obese subjects."
  *N Engl J Med* 1992; 327:1893–8. (Obese cohort: ≈47% under-report.)
- Hill RJ, Davies PSW. "The validity of self-reported energy intake as
  determined using the doubly labelled water technique." *Br J Nutr* 2001;
  85:415–30. (Lean cohort: ≈10-15% under-report.)
- Schoeller DA. "Limitations in the assessment of dietary energy intake by
  self-report." *Metabolism* 1995; 44(2 Suppl 2):18–22. (Overweight ≈20%.)

We expose conservative bucketed multipliers (lean / overweight / obese) and
apply them BEFORE the TDEE-observed = mean(kcal_in) − slope·7700 equation in
recalibration. Always inflationary — correction never reduces raw intake.

Pure domain. Decimal-only. No I/O, no framework.
"""

from __future__ import annotations

import logging
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Final

_logger = logging.getLogger(__name__)

_TWO_DP: Final[Decimal] = Decimal("0.01")

BIAS_MULTIPLIERS: Final[dict[str, Decimal]] = {
    "lean": Decimal("1.10"),  # BMI < 25
    "overweight": Decimal("1.20"),  # 25 ≤ BMI < 30
    "obese": Decimal("1.30"),  # BMI ≥ 30
}

_BMI_OVERWEIGHT: Final[Decimal] = Decimal("25")
_BMI_OBESE: Final[Decimal] = Decimal("30")


def _bucket_for(bmi: Decimal) -> str:
    if bmi >= _BMI_OBESE:
        return "obese"
    if bmi >= _BMI_OVERWEIGHT:
        return "overweight"
    return "lean"


def corrected_kcal_in(*, raw_kcal: Decimal, bmi: Decimal) -> Decimal:
    """Return raw_kcal × bias_multiplier(bmi) (Decimal, 2dp half-even).

    Always ≥ raw_kcal; under-report bias is one-sided in the literature
    (Lichtman 1992; Hill 2001).
    """
    bucket = _bucket_for(bmi)
    multiplier = BIAS_MULTIPLIERS[bucket]
    corrected = (raw_kcal * multiplier).quantize(_TWO_DP, rounding=ROUND_HALF_EVEN)
    # D8 — PII hygiene. The bucket (lean / overweight / obese) is sufficient
    # for telemetry; raw BMI and kcal are personally-identifying biometrics
    # and must NOT land at INFO. DEBUG is verbose by design and disabled in
    # PROD, so engineers can still attach a debugger or set NOVA_LOG_LEVEL=
    # DEBUG locally without risking PII landing in shipped log streams.
    _logger.debug(
        "intake_bias_correction_applied bucket=%s multiplier=%s",
        bucket,
        multiplier,
    )
    return corrected
