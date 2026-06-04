"""Vision value objects — JobId, Confidence, VisionPrompt.

Confidence is a 0..1 ratio. Trigger threshold for auto-accepting a match
into food_logs is 0.7 (ADR-0003).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NewType
from uuid import UUID

JobId = NewType("JobId", UUID)


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
