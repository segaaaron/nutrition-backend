"""Unit tests for portion hint infrastructure (SqlPortionHintSource).

Tests _extract_keyword (pure) and load_hints (mocked DB).
"""
from __future__ import annotations

import asyncio
from collections.abc import Sequence
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.vision.domain.value_objects import FoodIdentification, PortionHint
from app.vision.infrastructure.portion_hint_source import SqlPortionHintSource, _extract_keyword

# ---------------------------------------------------------------------------
# _extract_keyword — pure function
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,expected", [
    ("pollo al horno", "pollo"),
    ("arroz con pollo", "arroz"),
    ("ensalada mixta", "ensalada"),
    ("huevo revuelto", "huevo"),
    ("pan integral", "pan"),            # "pan" < 4 chars but fallback; "integral" is stop
    ("agua", "agua"),                   # fallback: short word
    ("manzana", "manzana"),
    ("fideos salteados", "fideos"),
    ("sopa de lentejas", "sopa"),       # "sopa" is first meaningful word
    ("Pollo A LA Plancha", "pollo"),    # case-insensitive + accent strip
    ("brócoli al vapor", "brocoli"),    # accent stripped; "vapor" in stop words
])
def test_extract_keyword(name: str, expected: str) -> None:
    assert _extract_keyword(name) == expected


def test_extract_keyword_empty() -> None:
    assert _extract_keyword("") == ""


# ---------------------------------------------------------------------------
# SqlPortionHintSource.load_hints — mocked DB
# ---------------------------------------------------------------------------

def _mock_row(avg_g: float | None, kcal_per_100g: float | None):
    row = MagicMock()
    row.__getitem__ = lambda self, i: (avg_g, kcal_per_100g)[i]
    return row


@pytest.mark.asyncio
async def test_load_hints_returns_hint_on_match() -> None:
    session = MagicMock()
    # Simulate DB returning avg_g=150.0, kcal_per_100g=165.0 for "pollo"
    mock_result = MagicMock()
    mock_result.first.return_value = (150.0, 165.0)
    session.execute = AsyncMock(return_value=mock_result)

    src = SqlPortionHintSource(session)
    hints = await src.load_hints(["pollo al horno"])

    assert "pollo al horno" in hints
    hint = hints["pollo al horno"]
    assert isinstance(hint, PortionHint)
    assert hint.typical_serving_g == 150.0
    assert hint.kcal_per_100g == 165.0


@pytest.mark.asyncio
async def test_load_hints_skips_no_match() -> None:
    session = MagicMock()
    mock_result = MagicMock()
    mock_result.first.return_value = (None, None)
    session.execute = AsyncMock(return_value=mock_result)

    src = SqlPortionHintSource(session)
    hints = await src.load_hints(["ingrediente desconocido"])

    assert hints == {}


@pytest.mark.asyncio
async def test_load_hints_empty_input() -> None:
    session = MagicMock()
    session.execute = AsyncMock()

    src = SqlPortionHintSource(session)
    hints = await src.load_hints([])

    assert hints == {}
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_load_hints_partial_results() -> None:
    session = MagicMock()

    # "pollo" matches, "xyz" does not
    call_count = 0

    async def fake_execute(stmt, params):
        nonlocal call_count
        call_count += 1
        mock_result = MagicMock()
        if "pollo" in params.get("pattern", ""):
            mock_result.first.return_value = (180.0, None)
        else:
            mock_result.first.return_value = (None, None)
        return mock_result

    session.execute = fake_execute

    src = SqlPortionHintSource(session)
    hints = await src.load_hints(["pollo a la plancha", "xyz desconocido"])

    assert "pollo a la plancha" in hints
    assert "xyz desconocido" not in hints
    assert hints["pollo a la plancha"].typical_serving_g == 180.0
    assert hints["pollo a la plancha"].kcal_per_100g is None


@pytest.mark.asyncio
async def test_load_hints_db_error_silenced() -> None:
    session = MagicMock()
    session.execute = AsyncMock(side_effect=RuntimeError("DB down"))

    src = SqlPortionHintSource(session)
    # Should not raise — errors are caught per-query and logged
    hints = await src.load_hints(["pollo"])
    assert hints == {}


@pytest.mark.asyncio
async def test_load_hints_is_sequential_not_concurrent() -> None:
    """Regression: load_hints MUST serialise queries on the shared AsyncSession.

    A single AsyncSession is one connection and is NOT concurrency-safe;
    firing queries via asyncio.gather interleaves operations on the same
    connection → SQLAlchemy IllegalStateChangeError (the documented race at
    process_vision_job.py:163 / create_plan.py). This test fails if any two
    queries overlap in time — i.e. if someone reintroduces gather().
    """
    in_flight = 0
    max_in_flight = 0

    async def tracking_execute(stmt, params):
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        # Yield control so an overlapping (gathered) call would run here.
        await asyncio.sleep(0)
        in_flight -= 1
        mock_result = MagicMock()
        mock_result.first.return_value = (150.0, 165.0)
        return mock_result

    session = MagicMock()
    session.execute = tracking_execute

    src = SqlPortionHintSource(session)
    hints = await src.load_hints(
        ["pollo al horno", "arroz blanco", "brócoli al vapor", "salmón asado"]
    )

    assert len(hints) == 4
    assert max_in_flight == 1, (
        f"Queries overlapped (max_in_flight={max_in_flight}) — shared AsyncSession "
        "must be used sequentially, never via asyncio.gather"
    )


# ---------------------------------------------------------------------------
# RecognisePlate._load_hints integration (hint_source wiring)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recognise_plate_uses_hint_source() -> None:
    """RecognisePlate passes names to hint_source and maps results by index."""
    from unittest.mock import MagicMock

    from app.vision.application.recognise_plate import RecognisePlate

    hint = PortionHint(name_norm="pollo", typical_serving_g=180.0, kcal_per_100g=165.0)

    class FakeHintSource:
        async def load_hints(self, names: Sequence[str]):
            return {n: hint for n in names if "pollo" in n.lower()}

    ids = [
        FoodIdentification(name="pollo al horno", confidence=0.9, group="protein"),
        FoodIdentification(name="arroz blanco", confidence=0.8, group="grain"),
    ]

    provider = MagicMock()
    plate = RecognisePlate(
        identifier=provider,
        estimator=provider,
        hint_source=FakeHintSource(),
    )

    result = await plate._load_hints(ids)

    assert 0 in result  # pollo al horno (index 0) matched
    assert 1 not in result  # arroz (index 1) did not match
    assert result[0].typical_serving_g == 180.0


@pytest.mark.asyncio
async def test_recognise_plate_no_hint_source_returns_empty() -> None:
    """hint_source=None → _load_hints returns {}."""
    from unittest.mock import MagicMock

    from app.vision.application.recognise_plate import RecognisePlate

    provider = MagicMock()
    plate = RecognisePlate(identifier=provider, estimator=provider)  # no hint_source

    ids = [FoodIdentification(name="pollo", confidence=0.9, group="protein")]
    result = await plate._load_hints(ids)
    assert result == {}
