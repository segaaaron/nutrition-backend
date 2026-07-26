"""Unit tests for _resolve_region — country → ISO-3166-1 alpha-2 mapping."""
from __future__ import annotations

import pytest

from app.vision.application.process_vision_job import _resolve_region


@pytest.mark.parametrize(
    "country, fallback, expected",
    [
        # Landlocked LATAM — must map correctly so landlocked hint fires
        ("Bolivia", "latam", "BO"),
        ("bolivia", "latam", "BO"),
        ("BO", "latam", "BO"),
        ("Paraguay", "latam", "PY"),
        ("paraguay", "latam", "PY"),
        ("PY", "latam", "PY"),
        # Coastal LATAM — map to ISO, not landlocked
        ("Mexico", "latam", "MX"),
        ("Perú", "latam", "PE"),
        ("Chile", "latam", "CL"),
        ("Brasil", "latam", "BR"),
        # Unknown country → fallback
        ("Wakanda", "latam", "latam"),
        ("", "latam", "latam"),
        # None → fallback
        (None, "latam", "latam"),
        # Whitespace stripped
        ("  Bolivia  ", "latam", "BO"),
    ],
)
def test_resolve_region(country: str | None, fallback: str, expected: str) -> None:
    assert _resolve_region(country, fallback=fallback) == expected


def test_resolve_region_custom_fallback() -> None:
    assert _resolve_region(None, fallback="us") == "us"
    assert _resolve_region("unknown", fallback="eu") == "eu"
