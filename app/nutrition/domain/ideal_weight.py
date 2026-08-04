"""Ideal weight engine — Peterson (2016) + WHO BMI range + Devine reference.

Primary formula: Peterson CM et al. (2016). "Universal equation for estimating
ideal body weight and body weight at any BMI." Am J Clin Nutr 103(5):1197-203.
doi:10.3945/ajcn.115.121178. Validated on NHANES data; mean error 0.5-0.7%.

Supporting:
  - WHO BMI healthy range: 18.5–24.9 kg/m² (min/max of saludable zone).
  - Devine formula (1974): classical reference point; widely known by users.
    Originally Devine BJ, Gentamicin therapy. Drug Intell Clin Pharm 1974;8:650.
  - LATAM context note: Hispanic/Latino populations exhibit misclassification at
    standard cutoffs. Novel BMI cutoff ≥27.2 kg/m² for older Hispanic adults
    (Sci Reports 2024, PMC11555080). Note surfaced for BMI 25.0–27.9.

All arithmetic is Decimal-first (no float). Sex must be "male" or "female".
Height must be > 100 cm. Weight must be > 0 kg.

Invariants (enforced, not just asserted):
  - ideal_weight_min_kg < peterson_ideal_kg < ideal_weight_max_kg
  - devine_reference_kg ∈ [30, 140] for height ∈ [145, 215] cm
  - bmi_category is a member of BMI_CATEGORIES
  - pregnancy → weight_gap_direction = "maintain", estimated_weeks = None
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Final, Literal

# ── Constants ────────────────────────────────────────────────────────────────

_BMI_UNDERWEIGHT: Final = Decimal("18.5")
_BMI_HEALTHY_MAX: Final = Decimal("24.9")
_BMI_OBESE_MIN: Final = Decimal("30.0")  # WHO: obese ≥ 30.0 (overweight = 25.0–29.99)

# Peterson target BMI = centre of WHO healthy range
_PETERSON_TARGET_BMI: Final = Decimal("22.0")

# Conversion factor: inches per cm for Devine
_CM_PER_INCH: Final = Decimal("2.54")
_DEVINE_BASE_HEIGHT_CM: Final = Decimal("152.4")  # 5 feet in cm

BMI_CATEGORIES: Final = frozenset({"underweight", "healthy", "overweight", "obese"})
WEIGHT_DIRECTIONS: Final = frozenset({"lose", "gain", "maintain"})

# Safe weekly loss/gain rates (WHO/CDC/AHA consensus)
WEEKLY_RATES: Final[dict[str, Decimal]] = {
    "slow":     Decimal("0.25"),  # ~275 kcal deficit/day
    "moderate": Decimal("0.50"),  # ~550 kcal deficit/day — default
    "fast":     Decimal("1.00"),  # ~1100 kcal deficit/day — upper safe limit
}
DEFAULT_WEEKLY_RATE: Final = WEEKLY_RATES["moderate"]

_ONE: Final = Decimal("1")
_TWO: Final = Decimal("2")


# ── Domain types ─────────────────────────────────────────────────────────────

BmiCategory = Literal["underweight", "healthy", "overweight", "obese"]
WeightDirection = Literal["lose", "gain", "maintain"]


@dataclass(frozen=True, slots=True)
class WeightInsights:
    """All weight-related derived metrics for a user profile.

    Computed on-the-fly from biometrics — never stored in DB.
    """

    bmi: Decimal                          # 1 decimal place
    bmi_category: BmiCategory
    bmi_label_es: str

    ideal_weight_min_kg: Decimal          # WHO lower bound (BMI 18.5)
    ideal_weight_max_kg: Decimal          # WHO upper bound (BMI 24.9)
    peterson_ideal_kg: Decimal            # Peterson 2016 — most accurate point estimate
    devine_reference_kg: Decimal | None   # Devine 1974 — classical reference

    weight_to_lose_kg: Decimal | None     # None if already in range or pregnancy
    weight_gap_direction: WeightDirection
    weekly_rate_kg: Decimal
    weekly_rate_label: str
    estimated_weeks: int | None           # None if in healthy range or pregnancy
    estimated_date: date | None           # None if no goal

    latam_context_note: bool              # True when BMI 25.0–27.9 (LATAM misclassification zone)


# ── Internal helpers ─────────────────────────────────────────────────────────

def _q1(value: Decimal) -> Decimal:
    """Round to 1 decimal place, half-even."""
    return value.quantize(Decimal("0.1"), rounding=ROUND_HALF_EVEN)


def _q2(value: Decimal) -> Decimal:
    """Round to 2 decimal places, half-even."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


def _bmi_label_es(category: BmiCategory) -> str:
    return {
        "underweight": "Bajo peso",
        "healthy":     "Peso saludable",
        "overweight":  "Sobrepeso",
        "obese":       "Obesidad",
    }[category]


# ── Public functions ─────────────────────────────────────────────────────────

def compute_bmi(*, weight_kg: Decimal, height_cm: Decimal) -> Decimal:
    """BMI = weight_kg / height_m². Rounded to 1dp."""
    if weight_kg <= 0 or height_cm <= 0:
        raise ValueError(f"invalid biometrics: weight_kg={weight_kg} height_cm={height_cm}")
    height_m = height_cm / Decimal("100")
    return _q1(weight_kg / (height_m * height_m))


def classify_bmi(bmi: Decimal) -> BmiCategory:
    """WHO BMI categories. Obese threshold is ≥ 30.0 (not > 29.9)."""
    if bmi < _BMI_UNDERWEIGHT:
        return "underweight"
    if bmi <= _BMI_HEALTHY_MAX:
        return "healthy"
    if bmi < _BMI_OBESE_MIN:
        return "overweight"
    return "obese"


def compute_ideal_weight_range(*, height_cm: Decimal) -> tuple[Decimal, Decimal]:
    """WHO healthy weight range: [BMI 18.5, BMI 24.9] for this height.

    Returns (min_kg, max_kg) rounded to 2dp.
    """
    height_m = height_cm / Decimal("100")
    h2 = height_m * height_m
    return _q2(h2 * _BMI_UNDERWEIGHT), _q2(h2 * _BMI_HEALTHY_MAX)


def compute_peterson_ideal(*, height_cm: Decimal) -> Decimal:
    """Peterson (2016) universal IBW at BMI_target=22.0 kg/m².

    Formula: IBW = 2.2 × BMI_t + 3.5 × BMI_t × (height_m − 1.5)
    Mean error ≤ 0.7% on NHANES data (AJCN 2016, doi:10.3945/ajcn.115.121178).
    """
    height_m = height_cm / Decimal("100")
    bmi_t = _PETERSON_TARGET_BMI
    ibw = Decimal("2.2") * bmi_t + Decimal("3.5") * bmi_t * (height_m - Decimal("1.5"))
    return _q2(ibw)


def compute_devine_reference(*, height_cm: Decimal, sex: str) -> Decimal | None:
    """Devine (1974) classical IBW reference.

    Returns None for height < 152.4 cm (formula undefined below 5 feet).
    Hombres: 50.0 + 2.3 × (height_cm − 152.4) / 2.54
    Mujeres: 45.5 + 2.3 × (height_cm − 152.4) / 2.54
    """
    if height_cm < _DEVINE_BASE_HEIGHT_CM:
        return None
    base = Decimal("50.0") if sex == "male" else Decimal("45.5")
    inches_over = (height_cm - _DEVINE_BASE_HEIGHT_CM) / _CM_PER_INCH
    return _q2(base + Decimal("2.3") * inches_over)


def compute_weight_insights(
    *,
    weight_kg: Decimal,
    height_cm: Decimal,
    sex: str,
    goal: str,
    is_pregnant: bool = False,
    weekly_rate_kg: Decimal = DEFAULT_WEEKLY_RATE,
    today: date | None = None,
) -> WeightInsights:
    """Compute all weight insights for a user profile.

    Args:
        weight_kg: Current weight in kg.
        height_cm: Height in cm (must be > 100).
        sex: "male" or "female".
        goal: User goal ("weight_loss", "muscle_gain", "weight_maintenance", etc.)
        is_pregnant: If True, direction forced to "maintain" and timeline suppressed.
        weekly_rate_kg: Loss/gain rate. Default 0.5 kg/week (WHO moderate).
        today: Reference date for estimated_date. Defaults to date.today().
    """
    if weekly_rate_kg not in WEEKLY_RATES.values():
        raise ValueError(f"weekly_rate_kg must be one of {list(WEEKLY_RATES.values())}")

    _today = today or date.today()

    bmi = compute_bmi(weight_kg=weight_kg, height_cm=height_cm)
    category = classify_bmi(bmi)
    ideal_min, ideal_max = compute_ideal_weight_range(height_cm=height_cm)
    peterson = compute_peterson_ideal(height_cm=height_cm)
    devine = compute_devine_reference(height_cm=height_cm, sex=sex)

    # Pregnancy → no weight loss goal regardless of declared goal
    if is_pregnant:
        return WeightInsights(
            bmi=bmi,
            bmi_category=category,
            bmi_label_es=_bmi_label_es(category),
            ideal_weight_min_kg=ideal_min,
            ideal_weight_max_kg=ideal_max,
            peterson_ideal_kg=peterson,
            devine_reference_kg=devine,
            weight_to_lose_kg=None,
            weight_gap_direction="maintain",
            weekly_rate_kg=weekly_rate_kg,
            weekly_rate_label=_rate_label(weekly_rate_kg),
            estimated_weeks=None,
            estimated_date=None,
            latam_context_note=_latam_note(bmi),
        )

    # Determine gap and direction
    if category == "healthy":
        delta = None
        direction: WeightDirection = "maintain"
    elif category in ("overweight", "obese"):
        # Gap = distance to top of healthy range
        delta = _q2(weight_kg - ideal_max)
        direction = "lose"
    else:  # underweight
        # Gap = distance to bottom of healthy range
        delta = _q2(ideal_min - weight_kg)
        direction = "gain"

    # Override direction to "maintain" if goal is maintenance regardless of BMI
    if goal in ("weight_maintenance", "maintain"):
        delta = None
        direction = "maintain"

    # Timeline
    if delta is not None and delta > 0:
        weeks = int((delta / weekly_rate_kg).to_integral_value(rounding=ROUND_HALF_EVEN))
        est_date = _today + timedelta(weeks=weeks)
    else:
        weeks = None
        est_date = None

    return WeightInsights(
        bmi=bmi,
        bmi_category=category,
        bmi_label_es=_bmi_label_es(category),
        ideal_weight_min_kg=ideal_min,
        ideal_weight_max_kg=ideal_max,
        peterson_ideal_kg=peterson,
        devine_reference_kg=devine,
        weight_to_lose_kg=delta,
        weight_gap_direction=direction,
        weekly_rate_kg=weekly_rate_kg,
        weekly_rate_label=_rate_label(weekly_rate_kg),
        estimated_weeks=weeks,
        estimated_date=est_date,
        latam_context_note=_latam_note(bmi),
    )


def _rate_label(rate: Decimal) -> str:
    for label, val in WEEKLY_RATES.items():
        if rate == val:
            return label
    return "custom"


def _latam_note(bmi: Decimal) -> bool:
    # Sci Reports 2024 (PMC11555080): Hispanic/Latino adults show real
    # metabolic risk starting at BMI ≥27.2, not ≥30. Surface a note
    # in the 25.0–27.9 zone where standard classification says "overweight"
    # but the LATAM evidence suggests elevated risk nearer to 27+.
    return Decimal("25.0") <= bmi <= Decimal("27.9")
