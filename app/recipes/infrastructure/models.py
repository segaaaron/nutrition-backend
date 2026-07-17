"""SQLAlchemy ORM for recipes/recipe_components/foods.

Matches migration 0001 (§7). Uses pgvector's Vector type for the 1536-dim
embedding column. selectinload is the default hydration strategy used by the
repositories to avoid N+1 on components.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, CHAR, JSONB
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.identity.infrastructure.models import Base

# Native Postgres enums (migration 0001). `create_type=False` prevents
# duplicate CREATE TYPE on metadata.create_all and tells asyncpg to bind
# values as enum (not VARCHAR), avoiding DatatypeMismatchError on INSERT.
_MEAL_TIME_ENUM = PG_ENUM(
    "breakfast", "lunch", "dinner", "snack", name="meal_time_enum", create_type=False
)
_GOAL_ENUM = PG_ENUM(
    "weight_loss",
    "maintain",
    "muscle_gain",
    "weight_gain",
    "health",
    name="goal_enum",
    create_type=False,
)
_ALLERGEN_ENUM = PG_ENUM(
    "dairy",
    "gluten",
    "tree_nuts",
    "peanuts",
    "shellfish",
    "fish",
    "egg",
    "soy",
    "sesame",
    "celery",
    "mustard",
    "lupin",
    "sulphites",
    "molluscs",
    name="allergen_enum",
    create_type=False,
)


class FoodModel(Base):
    __tablename__ = "foods"
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    name_en: Mapped[str] = mapped_column(Text, nullable=False)
    name_norm: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name_translations: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    brand: Mapped[str | None] = mapped_column(Text, nullable=True)
    country: Mapped[str | None] = mapped_column(CHAR(2), nullable=True)
    portion_g: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    kcal: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    protein_g: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    carbs_g: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    fat_g: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    fiber_g: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    sugar_g: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    sodium_mg: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    sat_fat_g: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    micronutrients: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    barcode: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RecipeModel(Base):
    __tablename__ = "recipes"
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    name_en: Mapped[str] = mapped_column(Text, nullable=False)
    name_translations: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    description_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_translations: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    kcal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    protein_g: Mapped[int | None] = mapped_column(Integer, nullable=True)
    carbs_g: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fat_g: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Nullable since migration 0028. NULL = "not yet measured" (unknown);
    # a real 0 is an explicit measured zero. No DEFAULT so an INSERT that
    # omits the value stores NULL (unknown) rather than a fake 0 that would
    # silently pass "<= max" safety gates. See condition_gates fail-closed.
    fiber_g: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sugar_g: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sodium_mg: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sat_fat_g: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    meal_time: Mapped[str | None] = mapped_column(_MEAL_TIME_ENUM, nullable=True)
    prep_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    instructions_en: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    instructions_translations: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    verified_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_batch: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_catalog: Mapped[str | None] = mapped_column(Text, nullable=True)
    regions: Mapped[list[str]] = mapped_column(ARRAY(CHAR(5)), default=list)
    allergens: Mapped[list[str]] = mapped_column(ARRAY(_ALLERGEN_ENUM), default=list)
    recommended_conditions: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    contraindicated_conditions: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    target_goals: Mapped[list[str]] = mapped_column(ARRAY(_GOAL_ENUM), default=list)
    # Dietary pattern flags (migration 0017). NULL = unclassified → Layer 1
    # excludes for vegan/vegetarian users (fail-safe). Backfilled from
    # ingredients by scripts/backfill_diet_flags.py.
    is_vegetarian: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_vegan: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # True = contains land-animal meat (not fish/seafood). Used by Layer1 for
    # pescatarian filter. NULL treated as True (fail-safe: exclude until
    # classified). Backfilled by migration 0022.
    contains_meat: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # ISO-3166-1 alpha-2 codes of countries where this recipe must NOT be served
    # (migration 0025). Empty array = available everywhere. Plan Layer 1 filters
    # via NOT (:country = ANY(excluded_countries)). GIN-indexed for speed.
    excluded_countries: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}", default=list)
    # Quarantine (migration 0031). Non-NULL = stored nutrition is known-wrong,
    # so Layer1 must never serve this recipe in a new plan. Set for the
    # `meals_v4` batch, whose duplicated components inflated its macros.
    # Lifted by setting back to NULL once the recipe is re-authored and its
    # macros recomputed from real reference values.
    quarantined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    quarantine_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # v3 catalog fields (migration 0019). NULL for pre-v3 legacy recipes.
    cuisine: Mapped[str | None] = mapped_column(Text, nullable=True)
    dish_family: Mapped[str | None] = mapped_column(Text, nullable=True)
    scale_min: Mapped[float | None] = mapped_column(Numeric(5, 3), nullable=True)
    scale_max: Mapped[float | None] = mapped_column(Numeric(5, 3), nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    components: Mapped[list[RecipeComponentModel]] = relationship(
        "RecipeComponentModel",
        foreign_keys="RecipeComponentModel.recipe_id",
        cascade="all, delete-orphan",
        order_by="RecipeComponentModel.position",
        lazy="select",
    )


class RecipeComponentModel(Base):
    __tablename__ = "recipe_components"
    __table_args__ = (
        CheckConstraint(
            "food_id IS NOT NULL OR sub_recipe_id IS NOT NULL OR free_text_name IS NOT NULL",
            name="ck_component_payload",
        ),
    )
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    recipe_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("recipes.id", ondelete="CASCADE")
    )
    food_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("foods.id", ondelete="RESTRICT"), nullable=True
    )
    sub_recipe_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("recipes.id", ondelete="RESTRICT"), nullable=True
    )
    free_text_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    # English translation of free_text_name (BE-9). Backfilled from
    # data/ingredient_translations_es_en.json in migration 0030; NULL when no
    # translation exists → API falls back to free_text_name (mostly ES).
    name_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount_g: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    modifier: Mapped[str | None] = mapped_column(Text, nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
