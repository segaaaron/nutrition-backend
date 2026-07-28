"""Integration test for SqlPortionHintSource against a REAL AsyncSession.

This is the test that would have caught the shared-session concurrency bug:
unit tests mock `session.execute` as an independently-awaitable coroutine, so
they never reproduce the single-connection lock. Here we run load_hints over a
multi-item list on a real asyncpg connection — if load_hints ever reintroduces
`asyncio.gather` over the shared session, this raises IllegalStateChangeError /
InterfaceError instead of returning hints.

Run with: pytest tests/integration/vision/test_portion_hint_source_db.py -m integration
"""
from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import text

from app.vision.infrastructure.portion_hint_source import SqlPortionHintSource

pytestmark = pytest.mark.integration


async def _seed_recipe_components(session: Any) -> uuid.UUID:
    """Insert one recipe + free-text components (food_id NULL, like the catalog)."""
    recipe_id = uuid.uuid4()
    await session.execute(
        text("INSERT INTO recipes (id, name_en) VALUES (:id, :n)"),
        {"id": str(recipe_id), "n": f"hint-test-{recipe_id}"},
    )
    rows = [
        ("pollo a la plancha", 150.0),
        ("pollo asado", 170.0),      # second "pollo" row → AVG exercised
        ("arroz blanco cocido", 180.0),
        ("brócoli al vapor", 90.0),
        ("salmón al horno", 140.0),
    ]
    for name, grams in rows:
        await session.execute(
            text(
                "INSERT INTO recipe_components "
                "(id, recipe_id, free_text_name, amount_g) "
                "VALUES (:id, :rid, :name, :g)"
            ),
            {"id": str(uuid.uuid4()), "rid": str(recipe_id), "name": name, "g": grams},
        )
    await session.commit()
    return recipe_id


@pytest.mark.asyncio
async def test_load_hints_multi_item_real_session(db_session: Any) -> None:
    """Multi-item load_hints on a real session must not raise and must return hints.

    Reproduces the exact production path (2-8 items sharing one AsyncSession).
    With the buggy asyncio.gather version this raised on the real connection;
    the sequential version returns catalog-derived serving sizes.
    """
    recipe_id = await _seed_recipe_components(db_session)
    try:
        src = SqlPortionHintSource(db_session)
        names = [
            "pollo a la plancha",
            "arroz blanco",
            "brócoli al vapor",
            "salmón asado",
            "ingrediente inexistente xyz",
        ]

        hints = await src.load_hints(names)

        # Matched ingredients return a serving size; the unknown one is omitted.
        assert "pollo a la plancha" in hints
        assert "ingrediente inexistente xyz" not in hints
        # "pollo" keyword LIKE-matches both pollo rows → AVG(150,170)=160.
        assert hints["pollo a la plancha"].typical_serving_g == pytest.approx(160.0, abs=0.1)
        # Free-text catalog rows have food_id NULL, so kcal density is unpopulated.
        assert hints["pollo a la plancha"].kcal_per_100g is None
        # Every returned hint carries a positive serving weight.
        for h in hints.values():
            assert h.typical_serving_g is not None and h.typical_serving_g > 0
    finally:
        await db_session.execute(
            text("DELETE FROM recipe_components WHERE recipe_id = :rid"),
            {"rid": str(recipe_id)},
        )
        await db_session.execute(
            text("DELETE FROM recipes WHERE id = :rid"), {"rid": str(recipe_id)}
        )
        await db_session.commit()


@pytest.mark.asyncio
async def test_load_hints_empty_names_real_session(db_session: Any) -> None:
    """Empty input short-circuits without touching the DB."""
    src = SqlPortionHintSource(db_session)
    assert await src.load_hints([]) == {}
