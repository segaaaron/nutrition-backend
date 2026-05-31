"""Async SQLAlchemy repositories for recipes + foods.

Performance contract:
- `selectinload(RecipeModel.components)` everywhere — no N+1.
- Cursor pagination keyed by `(score DESC, id ASC)`; ASC tie-break makes the
  cursor stable when ties occur (otherwise pagination duplicates rows).
- GIN array filters use `&&` (overlap) for `regions`/`tags`/`target_goals`
  and `NOT &&` for `allergens_exclude` — the hard exclusion rule (ADR-0001).
- Hybrid scoring blends trigram similarity (0.5) + vector cosine (0.5).
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import bindparam, select, text
from sqlalchemy.dialects.postgresql import ARRAY, CHAR, TEXT
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.recipes.domain.entities import Food, Recipe, RecipeComponent
from app.recipes.domain.value_objects import FoodSearchQuery, RecipeSearchQuery
from app.recipes.infrastructure.models import FoodModel, RecipeComponentModel, RecipeModel


def _recipe_from_model(m: RecipeModel, components: list[RecipeComponent] | None = None) -> Recipe:
    return Recipe(
        id=m.id, name_en=m.name_en, name_translations=dict(m.name_translations or {}),
        description_en=m.description_en,
        description_translations=dict(m.description_translations or {}),
        image_url=m.image_url, kcal=m.kcal, protein_g=m.protein_g,
        carbs_g=m.carbs_g, fat_g=m.fat_g,
        fiber_g=m.fiber_g, sugar_g=m.sugar_g, sodium_mg=m.sodium_mg, sat_fat_g=m.sat_fat_g,
        tags=list(m.tags or []),
        meal_time=m.meal_time,  # type: ignore[arg-type]
        prep_min=m.prep_min,
        instructions_en=list(m.instructions_en or []),
        instructions_translations=dict(m.instructions_translations or {}),
        regions=list(m.regions or []), allergens=list(m.allergens or []),
        recommended_conditions=list(m.recommended_conditions or []),
        contraindicated_conditions=list(m.contraindicated_conditions or []),
        target_goals=list(m.target_goals or []),
        components=components if components is not None else [
            _component_from_model(c) for c in (m.components or [])
        ],
        created_at=m.created_at,
    )


def _component_from_model(c: RecipeComponentModel) -> RecipeComponent:
    return RecipeComponent(
        id=c.id, recipe_id=c.recipe_id, food_id=c.food_id, sub_recipe_id=c.sub_recipe_id,
        free_text_name=c.free_text_name, amount_g=c.amount_g, modifier=c.modifier,
        position=c.position,
    )


def _food_from_model(m: FoodModel) -> Food:
    return Food(
        id=m.id, name_en=m.name_en, name_norm=m.name_norm,
        name_translations=dict(m.name_translations or {}),
        brand=m.brand, country=m.country, portion_g=m.portion_g,
        kcal=m.kcal, protein_g=m.protein_g, carbs_g=m.carbs_g, fat_g=m.fat_g,
        fiber_g=m.fiber_g, sugar_g=m.sugar_g, sodium_mg=m.sodium_mg, sat_fat_g=m.sat_fat_g,
        micronutrients=dict(m.micronutrients) if m.micronutrients else None,
        barcode=m.barcode, verified=m.verified, source=m.source,
    )


class SqlRecipeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def get(self, recipe_id: UUID, *, hydrate_components: bool = True) -> Recipe | None:
        stmt = select(RecipeModel).where(RecipeModel.id == recipe_id)
        if hydrate_components:
            stmt = stmt.options(selectinload(RecipeModel.components))
        m = (await self.s.execute(stmt)).scalar_one_or_none()
        return _recipe_from_model(m) if m else None

    async def get_many(self, recipe_ids: list[UUID]) -> list[Recipe]:
        if not recipe_ids:
            return []
        stmt = (
            select(RecipeModel)
            .where(RecipeModel.id.in_(recipe_ids))
            .options(selectinload(RecipeModel.components))
        )
        rows = (await self.s.execute(stmt)).scalars().all()
        return [_recipe_from_model(m) for m in rows]

    async def search(self, query: RecipeSearchQuery) -> list[tuple[Recipe, float]]:
        """Trigram-only search (semantic_search adds the vector signal)."""
        # We use raw SQL so trigram similarity + array overlap filters compose
        # cleanly. SQLAlchemy Core doesn't expose `&&` cleanly across array
        # element types (mixing CHAR(5)[] vs text[] casts).
        params: dict[str, object] = {
            "limit": query.limit,
            "regions": query.regions or [],
            "allergens_exclude": query.allergens_exclude or [],
            "tags": query.tags or [],
            "goals": query.target_goals or [],
            "conditions": query.conditions or [],
            "max_kcal": query.max_kcal,
            "min_protein": query.min_protein_g,
            "meal_time": query.meal_time,
            "q": query.q,
            "cursor_id": query.cursor_last_id,
            "cursor_score": query.cursor_last_score,
        }
        where: list[str] = []
        if query.regions:
            where.append("r.regions && CAST(:regions AS char(5)[])")
        if query.allergens_exclude:
            where.append("NOT (r.allergens && CAST(:allergens_exclude AS text[]))")
        if query.tags:
            where.append("r.tags && CAST(:tags AS text[])")
        if query.target_goals:
            where.append("r.target_goals && CAST(:goals AS goal_enum[])")
        if query.conditions:
            # Hard-exclude any recipe whose contraindications overlap user's conditions.
            where.append("NOT (r.contraindicated_conditions && CAST(:conditions AS text[]))")
        if query.meal_time:
            where.append("r.meal_time = :meal_time")
        if query.max_kcal is not None:
            where.append("r.kcal <= :max_kcal")
        if query.min_protein_g is not None:
            where.append("r.protein_g >= :min_protein")

        score_expr = (
            "GREATEST(similarity(r.name_en, :q), 0.0)" if query.q else "0.0"
        )
        if query.cursor_last_score is not None and query.cursor_last_id:
            where.append(
                f"({score_expr}, r.id::text) < (:cursor_score, :cursor_id)"
            )
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        sql = f"""
            SELECT r.*, {score_expr} AS score
              FROM recipes r
              {where_sql}
             ORDER BY score DESC, r.id ASC
             LIMIT :limit
        """
        res = await self.s.execute(text(sql), params)
        rows = list(res.mappings())
        if not rows:
            return []
        ids = [r["id"] for r in rows]
        recipes = await self.get_many(ids)
        by_id = {r.id: r for r in recipes}
        out: list[tuple[Recipe, float]] = []
        for r in rows:
            rec = by_id.get(r["id"])
            if rec:
                out.append((rec, float(r["score"])))
        return out

    async def semantic_search(
        self, embedding: list[float], query: RecipeSearchQuery
    ) -> list[tuple[Recipe, float]]:
        """Hybrid: 0.5 * trigram + 0.5 * (1 - cosine_distance)."""
        params: dict[str, object] = {
            "limit": query.limit,
            "regions": query.regions or [],
            "allergens_exclude": query.allergens_exclude or [],
            "tags": query.tags or [],
            "goals": query.target_goals or [],
            "conditions": query.conditions or [],
            "max_kcal": query.max_kcal,
            "min_protein": query.min_protein_g,
            "meal_time": query.meal_time,
            "q": query.q or "",
            "cursor_id": query.cursor_last_id,
            "cursor_score": query.cursor_last_score,
            "embedding": str(embedding),  # pgvector accepts '[...]' literal
        }
        where: list[str] = ["r.embedding IS NOT NULL"]
        if query.regions:
            where.append("r.regions && CAST(:regions AS char(5)[])")
        if query.allergens_exclude:
            where.append("NOT (r.allergens && CAST(:allergens_exclude AS text[]))")
        if query.tags:
            where.append("r.tags && CAST(:tags AS text[])")
        if query.target_goals:
            where.append("r.target_goals && CAST(:goals AS goal_enum[])")
        if query.conditions:
            where.append("NOT (r.contraindicated_conditions && CAST(:conditions AS text[]))")
        if query.meal_time:
            where.append("r.meal_time = :meal_time")
        if query.max_kcal is not None:
            where.append("r.kcal <= :max_kcal")
        if query.min_protein_g is not None:
            where.append("r.protein_g >= :min_protein")

        trgm = "GREATEST(similarity(r.name_en, :q), 0.0)" if query.q else "0.0"
        score_expr = (
            f"(0.5 * {trgm}) + 0.5 * (1.0 - (r.embedding <=> CAST(:embedding AS vector)))"
        )
        if query.cursor_last_score is not None and query.cursor_last_id:
            where.append(
                f"({score_expr}, r.id::text) < (:cursor_score, :cursor_id)"
            )
        where_sql = "WHERE " + " AND ".join(where)
        sql = f"""
            SELECT r.id, {score_expr} AS score
              FROM recipes r
              {where_sql}
             ORDER BY score DESC, r.id ASC
             LIMIT :limit
        """
        res = await self.s.execute(text(sql), params)
        scored = [(r["id"], float(r["score"])) for r in res.mappings()]
        if not scored:
            return []
        recipes = await self.get_many([rid for rid, _ in scored])
        by_id = {r.id: r for r in recipes}
        out: list[tuple[Recipe, float]] = []
        for rid, score in scored:
            rec = by_id.get(rid)
            if rec:
                out.append((rec, score))
        return out


class SqlFoodRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def get(self, food_id: UUID) -> Food | None:
        m = await self.s.get(FoodModel, food_id)
        return _food_from_model(m) if m else None

    async def get_by_barcode(self, ean: str) -> Food | None:
        stmt = select(FoodModel).where(FoodModel.barcode == ean)
        m = (await self.s.execute(stmt)).scalar_one_or_none()
        return _food_from_model(m) if m else None

    async def search(self, query: FoodSearchQuery) -> list[tuple[Food, float]]:
        params: dict[str, object] = {
            "limit": query.limit,
            "country": query.country,
            "q": query.q,
            "cursor_id": query.cursor_last_id,
            "cursor_score": query.cursor_last_score,
        }
        where: list[str] = []
        if query.country:
            where.append("(f.country = :country OR f.country IS NULL)")
        if query.verified_only:
            where.append("f.verified = true")
        score_expr = "GREATEST(similarity(f.name_norm, :q), 0.0)" if query.q else "0.0"
        if query.cursor_last_score is not None and query.cursor_last_id:
            where.append(f"({score_expr}, f.id::text) < (:cursor_score, :cursor_id)")
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        sql = f"""
            SELECT f.*, {score_expr} AS score
              FROM foods f
              {where_sql}
             ORDER BY score DESC, f.id ASC
             LIMIT :limit
        """
        res = await self.s.execute(text(sql), params)
        rows = list(res.mappings())
        out: list[tuple[Food, float]] = []
        for r in rows:
            m = await self.s.get(FoodModel, r["id"])
            if m:
                out.append((_food_from_model(m), float(r["score"])))
        return out
