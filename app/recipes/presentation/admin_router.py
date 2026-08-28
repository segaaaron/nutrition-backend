"""Admin endpoints for recipe image management.

Registered in main.py under prefix /admin:
  POST   /admin/recipes/{recipe_id}/image   — upload/replace image
  DELETE /admin/recipes/{recipe_id}/image   — remove image
  GET    /admin/recipes/images/pending      — list recipes without image
"""

from __future__ import annotations

import asyncio
from pathlib import Path as FilePath
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Path, Response, UploadFile, status
from sqlalchemy import text

from app.core.config import get_settings
from app.core.errors import NotFoundError
from app.identity.presentation.dependencies import SessionDep, require_admin
from app.imaging.infrastructure.vips_compressor import VipsImageCompressor
from app.recipes.application.upload_recipe_image import UploadRecipeImage
from app.recipes.presentation.schemas import PendingRecipeImageItem, RecipeImageOut

router = APIRouter(tags=["admin"])


def _delete_file(path: FilePath) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


@router.post(
    "/recipes/{recipe_id}/image",
    response_model=RecipeImageOut,
    status_code=status.HTTP_200_OK,
)
async def upload_recipe_image(
    recipe_id: Annotated[UUID, Path()],
    session: SessionDep,
    _admin: Annotated[UUID, require_admin],
    file: UploadFile = File(...),
) -> RecipeImageOut:
    raw = await file.read()
    uc = UploadRecipeImage(session=session, compressor=VipsImageCompressor())
    rid, image_url, size_kb = await uc(
        recipe_id=recipe_id,
        raw_bytes=raw,
        mime=file.content_type or "application/octet-stream",
    )
    return RecipeImageOut(recipe_id=rid, image_url=image_url, size_kb=size_kb)


@router.delete(
    "/recipes/{recipe_id}/image",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_recipe_image(
    recipe_id: Annotated[UUID, Path()],
    session: SessionDep,
    _admin: Annotated[UUID, require_admin],
) -> Response:
    row = (
        await session.execute(
            text("SELECT image_url FROM recipes WHERE id = :id"),
            {"id": str(recipe_id)},
        )
    ).mappings().first()
    if row is None:
        raise NotFoundError("recipe_not_found", recipe_id=str(recipe_id))

    image_url: str | None = row["image_url"]

    await session.execute(
        text("UPDATE recipes SET image_url = NULL WHERE id = :id"),
        {"id": str(recipe_id)},
    )

    if image_url:
        settings = get_settings()
        base = settings.recipe_image_base_url.rstrip("/")
        if image_url.startswith(base + "/"):
            rel = image_url[len(base) + 1:]
            disk_path = FilePath(settings.recipe_image_dir) / rel
            await asyncio.to_thread(_delete_file, disk_path)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/recipes/images/pending",
    response_model=list[PendingRecipeImageItem],
)
async def list_recipes_pending_image(
    session: SessionDep,
    _admin: Annotated[UUID, require_admin],
) -> list[PendingRecipeImageItem]:
    rows = (
        (
            await session.execute(
                text(
                    """
                    SELECT id,
                           name_translations->>'es' AS name_es,
                           meal_time
                      FROM recipes
                     WHERE image_url IS NULL
                     ORDER BY meal_time, name_translations->>'es'
                    """
                )
            )
        )
        .mappings()
        .all()
    )
    return [
        PendingRecipeImageItem(
            recipe_id=r["id"],
            name_es=r["name_es"],
            meal_time=r["meal_time"],
        )
        for r in rows
    ]
