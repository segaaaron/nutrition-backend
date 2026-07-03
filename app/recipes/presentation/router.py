"""Recipes router — /recipes, /recipes/{id}, /recipes/search/semantic,
/foods, /foods/barcode/{ean}.

Cursor pagination encoding: opaque base64-of-`{score}|{id}`. Clients echo it
back via `?cursor=...` (or in the JSON body for semantic search). The server
re-parses it into `(cursor_last_score, cursor_last_id)`.
"""

from __future__ import annotations

import base64
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Path, Query

from app.identity.presentation.dependencies import CurrentUserDep, SessionDep
from app.recipes.application.use_cases import (
    GetFoodByBarcode,
    GetRecipe,
    SearchFoods,
    SearchRecipes,
)
from app.recipes.domain.entities import Food, Recipe
from app.recipes.domain.value_objects import FoodSearchQuery, RecipeSearchQuery
from app.recipes.infrastructure.openai_embedder import OpenAIEmbedder
from app.recipes.infrastructure.repositories import SqlFoodRepository, SqlRecipeRepository
from app.recipes.presentation.schemas import (
    ComponentResponse,
    FoodListResponse,
    FoodResponse,
    RecipeListResponse,
    RecipeResponse,
    RecipeSemanticSearchRequest,
)

router = APIRouter(tags=["recipes"])
# BOLA EXEMPT: recipes, foods, and food-barcode endpoints are global catalog
# reads — no user_id column exists on these tables and no ownership check applies.
# Any authenticated (or unauthenticated in future) user may read them.


def _accept_lang(accept_language: str | None) -> str:
    if not accept_language:
        return "en"
    primary = accept_language.split(",")[0].strip().split("-")[0].lower()
    return primary if primary in ("en", "es", "pt", "fr", "de") else "en"


def _encode_cursor(score: float, recipe_id: UUID) -> str:
    raw = f"{score}|{recipe_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str | None) -> tuple[float, str] | tuple[None, None]:
    if not cursor:
        return None, None
    try:
        pad = "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(cursor + pad).decode()
        score, rid = raw.split("|", 1)
        return float(score), rid
    except Exception:  # noqa: BLE001
        return None, None


def _to_recipe_resp(r: Recipe, locale: str, score: float | None = None) -> RecipeResponse:
    return RecipeResponse(
        id=r.id,
        name=r.translated_name(locale),
        description=r.translated_description(locale),
        image_url=r.image_url,
        kcal=r.kcal,
        protein_g=r.protein_g,
        carbs_g=r.carbs_g,
        fat_g=r.fat_g,
        fiber_g=r.fiber_g,
        sugar_g=r.sugar_g,
        sodium_mg=r.sodium_mg,
        sat_fat_g=r.sat_fat_g,
        tags=r.tags,
        meal_time=r.meal_time,
        prep_min=r.prep_min,
        instructions=r.translated_instructions(locale),
        regions=r.regions,
        allergens=r.allergens,
        recommended_conditions=r.recommended_conditions,
        contraindicated_conditions=r.contraindicated_conditions,
        target_goals=r.target_goals,
        components=[
            ComponentResponse(
                id=c.id,
                food_id=c.food_id,
                sub_recipe_id=c.sub_recipe_id,
                free_text_name=c.free_text_name,
                amount_g=c.amount_g,
                modifier=c.modifier,
                position=c.position,
            )
            for c in r.components
        ],
        score=score,
    )


def _to_food_resp(f: Food, locale: str, score: float | None = None) -> FoodResponse:
    return FoodResponse(
        id=f.id,
        name=f.translated_name(locale),
        brand=f.brand,
        country=f.country,
        portion_g=f.portion_g,
        kcal=f.kcal,
        protein_g=f.protein_g,
        carbs_g=f.carbs_g,
        fat_g=f.fat_g,
        fiber_g=f.fiber_g,
        sugar_g=f.sugar_g,
        sodium_mg=f.sodium_mg,
        sat_fat_g=f.sat_fat_g,
        barcode=f.barcode,
        verified=f.verified,
        score=score,
    )


@router.get("/recipes", response_model=RecipeListResponse)
async def list_recipes(
    session: SessionDep,
    accept_language: Annotated[str | None, Header(alias="Accept-Language")] = None,
    q: str | None = Query(default=None, max_length=200),
    meal_time: Literal["breakfast", "lunch", "dinner", "snack"] | None = None,
    region: list[str] = Query(default_factory=list),
    allergen_exclude: list[str] = Query(default_factory=list),
    condition: list[str] = Query(default_factory=list),
    tag: list[str] = Query(default_factory=list),
    target_goal: list[str] = Query(default_factory=list),
    max_kcal: int | None = None,
    min_protein_g: int | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = None,
) -> RecipeListResponse:
    locale = _accept_lang(accept_language)
    last_score, last_id = _decode_cursor(cursor)
    query = RecipeSearchQuery(
        q=q,
        meal_time=meal_time,
        regions=region,
        allergens_exclude=allergen_exclude,
        conditions=condition,
        tags=tag,
        target_goals=target_goal,
        max_kcal=max_kcal,
        min_protein_g=min_protein_g,
        limit=limit,
        cursor_last_id=last_id,
        cursor_last_score=last_score,
    )
    uc = SearchRecipes(recipes=SqlRecipeRepository(session))
    results = await uc(query=query, semantic=False)
    items = [_to_recipe_resp(r, locale, s) for r, s in results]
    next_cursor = (
        _encode_cursor(results[-1][1], results[-1][0].id) if len(results) == limit else None
    )
    return RecipeListResponse(items=items, next_cursor=next_cursor)


@router.get("/recipes/{recipe_id}", response_model=RecipeResponse)
async def get_recipe(
    session: SessionDep,
    recipe_id: Annotated[UUID, Path()],
    accept_language: Annotated[str | None, Header(alias="Accept-Language")] = None,
) -> RecipeResponse:
    locale = _accept_lang(accept_language)
    uc = GetRecipe(recipes=SqlRecipeRepository(session))
    rec = await uc(recipe_id=recipe_id, locale=locale)
    return _to_recipe_resp(rec, locale)


@router.post("/recipes/search/semantic", response_model=RecipeListResponse)
async def search_semantic(
    body: RecipeSemanticSearchRequest,
    _current_user: CurrentUserDep,
    session: SessionDep,
    accept_language: Annotated[str | None, Header(alias="Accept-Language")] = None,
) -> RecipeListResponse:
    locale = _accept_lang(accept_language)
    last_score, last_id = _decode_cursor(body.cursor)
    query = RecipeSearchQuery(
        q=body.q,
        meal_time=body.meal_time,
        regions=body.regions,
        allergens_exclude=body.allergens_exclude,
        conditions=body.conditions,
        tags=body.tags,
        target_goals=body.target_goals,
        max_kcal=body.max_kcal,
        min_protein_g=body.min_protein_g,
        limit=body.limit,
        cursor_last_id=last_id,
        cursor_last_score=last_score,
    )
    uc = SearchRecipes(recipes=SqlRecipeRepository(session), embedder=OpenAIEmbedder())
    results = await uc(query=query, semantic=True)
    items = [_to_recipe_resp(r, locale, s) for r, s in results]
    next_cursor = (
        _encode_cursor(results[-1][1], results[-1][0].id) if len(results) == body.limit else None
    )
    return RecipeListResponse(items=items, next_cursor=next_cursor)


@router.get("/foods", response_model=FoodListResponse)
async def list_foods(
    session: SessionDep,
    accept_language: Annotated[str | None, Header(alias="Accept-Language")] = None,
    q: str | None = Query(default=None, max_length=200),
    country: str | None = Query(default=None, max_length=2),
    verified_only: bool = False,
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = None,
) -> FoodListResponse:
    locale = _accept_lang(accept_language)
    last_score, last_id = _decode_cursor(cursor)
    query = FoodSearchQuery(
        q=q,
        country=country,
        verified_only=verified_only,
        limit=limit,
        cursor_last_id=last_id,
        cursor_last_score=last_score,
    )
    uc = SearchFoods(foods=SqlFoodRepository(session))
    results = await uc(query=query)
    items = [_to_food_resp(f, locale, s) for f, s in results]
    next_cursor = (
        _encode_cursor(results[-1][1], results[-1][0].id) if len(results) == limit else None
    )
    return FoodListResponse(items=items, next_cursor=next_cursor)


@router.get("/foods/barcode/{ean}", response_model=FoodResponse)
async def get_food_barcode(
    session: SessionDep,
    ean: Annotated[str, Path(min_length=8, max_length=14)],
    accept_language: Annotated[str | None, Header(alias="Accept-Language")] = None,
) -> FoodResponse:
    locale = _accept_lang(accept_language)
    uc = GetFoodByBarcode(foods=SqlFoodRepository(session))
    f = await uc(ean=ean)
    return _to_food_resp(f, locale)
