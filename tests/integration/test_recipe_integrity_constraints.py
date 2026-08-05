"""The database must refuse the ten defect classes found in the 2026-08-04 audit.

Migration 0038 moved the catalog's consistency rules out of scripts and into
CHECK constraints. The distinction matters: a script check runs if someone
remembers to run it, and every one of those defects was written by a script
that believed it was correct. A constraint runs on every INSERT, in whatever
session wrote it, before the bad row exists.

This suite is the proof that the constraints are actually attached and actually
bite. It runs against the CI Postgres after `alembic upgrade head`, so a
migration that silently fails to apply them is caught on the next main push.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("DATABASE_URL"),
        reason="needs a live Postgres with migrations applied",
    ),
]

# Atwater-consistent macros, so a row is rejected only for the defect under test.
_P, _C, _F = 30, 50, 12
_KCAL = _P * 4 + _C * 4 + _F * 9


@pytest_asyncio.fixture
async def conn() -> AsyncIterator:
    import asyncpg

    dsn = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    connection = await asyncpg.connect(dsn)
    transaction = connection.transaction()
    await transaction.start()
    try:
        yield connection
    finally:
        # Everything these tests write is rolled back; CI's catalog is untouched.
        await transaction.rollback()
        await connection.close()


async def _insert(connection, columns: str, values: str, *args) -> None:
    await connection.execute(
        f"INSERT INTO recipes ({columns}) VALUES ({values})",  # noqa: S608
        *args,
    )


async def _expect_violation(connection, constraint: str, coro_factory) -> None:
    """Assert the statement trips `constraint`, inside a SAVEPOINT.

    A CheckViolation aborts the enclosing transaction, so without a savepoint
    every statement after the first expected failure dies with
    InFailedSQLTransactionError rather than its own constraint error.
    """
    import asyncpg

    savepoint = connection.transaction()
    await savepoint.start()
    try:
        with pytest.raises(asyncpg.exceptions.CheckViolationError) as exc:
            await coro_factory()
        assert exc.value.constraint_name == constraint, (
            f"expected {constraint}, got {exc.value.constraint_name}")
    finally:
        await savepoint.rollback()


@pytest.mark.asyncio
async def test_consistent_recipe_is_accepted(conn) -> None:
    """The constraints must not reject legitimate rows — otherwise every batch
    breaks and someone drops them."""
    await _insert(
        conn,
        "name_en, kcal, protein_g, carbs_g, fat_g, sugar_g, added_sugar_g, "
        "regions, recommended_conditions",
        "$1, $2, $3, $4, $5, $6, $7, $8::text[]::char(5)[], $9::text[]",
        "Valid row", _KCAL, _P, _C, _F, 9, 2, ["latam", "us"], ["fatty_liver"],
    )
    assert await conn.fetchval(
        "SELECT COUNT(*) FROM recipes WHERE name_en = 'Valid row'") == 1


@pytest.mark.asyncio
async def test_kcal_must_equal_atwater(conn) -> None:
    """15 snacks shipped storing kcal=130 against an Atwater value of 263-312.
    The engine scales portions by kcal, so those plans served roughly double
    what they counted."""
    import asyncpg

    with pytest.raises(asyncpg.exceptions.CheckViolationError) as exc:
        await _insert(
            conn, "name_en, kcal, protein_g, carbs_g, fat_g",
            "$1, $2, $3, $4, $5", "Lying kcal", 130, 9, 39, 10)
    assert exc.value.constraint_name == "ck_recipes_kcal_atwater"


@pytest.mark.asyncio
async def test_added_sugar_cannot_exceed_total_sugar(conn) -> None:
    import asyncpg

    with pytest.raises(asyncpg.exceptions.CheckViolationError) as exc:
        await _insert(conn, "name_en, sugar_g, added_sugar_g", "$1, $2, $3",
                      "Impossible sugar", 5, 9)
    assert exc.value.constraint_name == "ck_recipes_added_sugar_subset"


@pytest.mark.asyncio
async def test_negative_nutrients_are_rejected(conn) -> None:
    import asyncpg

    with pytest.raises(asyncpg.exceptions.CheckViolationError) as exc:
        await _insert(conn, "name_en, sodium_mg", "$1, $2", "Negative sodium", -10)
    assert exc.value.constraint_name == "ck_recipes_nutrition_nonneg"


@pytest.mark.asyncio
async def test_region_vocabulary_is_closed(conn) -> None:
    """Nine ISO country codes left by an abandoned retag script matched no
    market, making those recipes invisible to every user."""
    import asyncpg

    with pytest.raises(asyncpg.exceptions.CheckViolationError) as exc:
        await _insert(conn, "name_en, regions", "$1, $2::text[]::char(5)[]",
                      "Junk region", ["MX"])
    assert exc.value.constraint_name == "ck_recipes_regions_vocab"


@pytest.mark.asyncio
async def test_supported_markets_are_accepted(conn) -> None:
    """A market region_mapper can emit must never be rejected — that is how
    Canada ended up with zero recipes."""
    for market in ("latam", "us", "ca"):
        await _insert(conn, "name_en, regions", "$1, $2::text[]::char(5)[]",
                      f"Market {market}", [market])


@pytest.mark.asyncio
async def test_retired_conditions_are_rejected(conn) -> None:
    """REGLA #0.5.C closed the scope to three situations in July 2026, but
    1,137 recipes still carried the removed ones — and
    `recommended_conditions` is serialised straight into the API response."""
    for column, constraint in (
        ("recommended_conditions", "ck_recipes_rec_conditions_vocab"),
        ("contraindicated_conditions", "ck_recipes_con_conditions_vocab"),
    ):
        await _expect_violation(
            conn, constraint,
            lambda col=column: _insert(
                conn, f"name_en, {col}", "$1, $2::text[]",
                f"Retired via {col}", ["diabetes"]),
        )


@pytest.mark.asyncio
async def test_component_amount_must_be_positive(conn) -> None:
    """A zero-gram component contributes nothing, silently understating the
    recipe's nutrition."""
    import asyncpg

    recipe_id = await conn.fetchval(
        "INSERT INTO recipes (name_en) VALUES ('Host') RETURNING id")
    with pytest.raises(asyncpg.exceptions.CheckViolationError) as exc:
        await conn.execute(
            "INSERT INTO recipe_components (recipe_id, free_text_name, amount_g) "
            "VALUES ($1, $2, $3)", recipe_id, "Ajo", 0)
    assert exc.value.constraint_name == "ck_recipe_components_amount_positive"


@pytest.mark.asyncio
async def test_component_name_must_not_be_blank(conn) -> None:
    """A blank name cannot resolve to USDA, so its nutrition is lost."""
    import asyncpg

    recipe_id = await conn.fetchval(
        "INSERT INTO recipes (name_en) VALUES ('Host 2') RETURNING id")
    with pytest.raises(asyncpg.exceptions.CheckViolationError) as exc:
        await conn.execute(
            "INSERT INTO recipe_components (recipe_id, free_text_name, amount_g) "
            "VALUES ($1, $2, $3)", recipe_id, "   ", 50)
    assert exc.value.constraint_name == "ck_recipe_components_name_present"


@pytest.mark.asyncio
async def test_aggregates_trigger_no_longer_zeroes_nutrition(conn) -> None:
    """Migration 0036. The trigger inner-joined `foods` on a NULL food_id, so
    its aggregate was empty and COALESCE(..., 0) wrote zeros over correct
    values — the root cause of `sodium_mg = 0` on 1,437 of 1,582 recipes.
    Inserting a free-text component must now leave nutrition untouched.
    """
    recipe_id = await conn.fetchval(
        "INSERT INTO recipes (name_en, kcal, protein_g, carbs_g, fat_g, "
        "fiber_g, sugar_g, sodium_mg, sat_fat_g) "
        "VALUES ('Trigger probe', $1, $2, $3, $4, 8, 6, 420, 4) RETURNING id",
        _KCAL, _P, _C, _F)
    await conn.execute(
        "INSERT INTO recipe_components (recipe_id, free_text_name, amount_g) "
        "VALUES ($1, $2, $3)", recipe_id, "Pechuga de pollo (cruda)", 200)

    row = await conn.fetchrow(
        "SELECT fiber_g, sugar_g, sodium_mg, sat_fat_g FROM recipes WHERE id = $1",
        recipe_id)
    assert (row["fiber_g"], row["sugar_g"], row["sodium_mg"], row["sat_fat_g"]) == (
        8, 6, 420, 4), "the aggregates trigger clobbered nutrition again"
