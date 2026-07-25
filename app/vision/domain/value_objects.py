"""Vision value objects — JobId, Confidence, VisionPrompt.

Confidence is a 0..1 ratio. Trigger threshold for auto-accepting a match
into food_logs is 0.7 (ADR-0003).

Two-pass pipeline value objects (added 2026-07-25):
- ``FoodIdentification`` — Call-1 output: WHAT is on the plate, no mass/energy.
- ``PortionEstimate``    — Call-2 output: grams + macros per identified item.
- ``PortionHint``        — Catalog-derived prior handed to Call-2 (never applied
                           directly to results).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, NewType
from uuid import UUID

from app.vision.domain.entities import FoodGroup

JobId = NewType("JobId", UUID)

PortionKind = Literal["pieza_entera", "a_granel"]


@dataclass(frozen=True, slots=True)
class Confidence:
    value: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.value <= 1.0:
            raise ValueError(f"confidence_out_of_range:{self.value}")


@dataclass(frozen=True, slots=True)
class VisionPrompt:
    """Hash-keyed system prompt for the vision call — keeps prompt versioning auditable."""

    body: str
    sha256: str
    locale: str = "en"
    region: str = "us"


# ---------------------------------------------------------------------------
# Two-pass pipeline value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FoodIdentification:
    """Call-1 output: WHAT is on the plate.  No mass, no energy."""

    name: str
    confidence: float          # 0..1, identity confidence only
    group: FoodGroup
    role: str | None = None
    prep_method: str | None = None
    count: int = 1
    portion_kind: PortionKind = "a_granel"
    bbox: tuple[float, float, float, float] | None = None
    inferred: bool = False

    def __post_init__(self) -> None:
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(
                f"confidence must be in [0, 1], got {self.confidence}"
            )
        if self.count < 1:
            raise ValueError(f"count must be >= 1, got {self.count}")


@dataclass(frozen=True, slots=True)
class PortionEstimate:
    """Call-2 output for ONE identification, addressed by index."""

    index: int
    estimated_amount_g: Decimal
    kcal: int
    protein_g: int
    carbs_g: int
    fat_g: int
    confidence: float          # SIZE confidence, orthogonal to identity conf

    def __post_init__(self) -> None:
        if self.index < 0:
            raise ValueError(f"index must be >= 0, got {self.index}")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(
                f"confidence must be in [0, 1], got {self.confidence}"
            )
        if not self.estimated_amount_g.is_finite() or self.estimated_amount_g <= 0:
            raise ValueError(
                f"estimated_amount_g must be finite and positive, got {self.estimated_amount_g}"
            )
        if self.kcal < 0:
            raise ValueError(f"kcal must be >= 0, got {self.kcal}")
        if self.protein_g < 0 or self.carbs_g < 0 or self.fat_g < 0:
            raise ValueError("macro grams must be >= 0")


@dataclass(frozen=True, slots=True)
class PortionHint:
    """Catalog-derived prior handed to Call 2.  Never applied directly to results."""

    name_norm: str
    typical_serving_g: float | None
    kcal_per_100g: float | None
