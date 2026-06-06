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
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, CHAR, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.identity.infrastructure.models import Base


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
    fiber_g: Mapped[int] = mapped_column(Integer, default=0)
    sugar_g: Mapped[int] = mapped_column(Integer, default=0)
    sodium_mg: Mapped[int] = mapped_column(Integer, default=0)
    sat_fat_g: Mapped[int] = mapped_column(Integer, default=0)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    meal_time: Mapped[str | None] = mapped_column(String(16), nullable=True)
    prep_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    instructions_en: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    instructions_translations: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    verified_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_batch: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_catalog: Mapped[str | None] = mapped_column(Text, nullable=True)
    regions: Mapped[list[str]] = mapped_column(ARRAY(CHAR(5)), default=list)
    allergens: Mapped[list[str]] = mapped_column(ARRAY(String(24)), default=list)
    recommended_conditions: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    contraindicated_conditions: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    target_goals: Mapped[list[str]] = mapped_column(ARRAY(String(16)), default=list)
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
    amount_g: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    modifier: Mapped[str | None] = mapped_column(Text, nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
