"""Use case: upload, compress, and persist a recipe image to local disk."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import NotFoundError, ValidationError
from app.imaging.domain.contracts import CompressionProfile, ImageCompressor

_ALLOWED_MIMES: frozenset[str] = frozenset({"image/jpeg", "image/png", "image/webp"})
_MAX_BYTES: int = 5 * 1024 * 1024


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _delete_file_if_exists(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


@dataclass(slots=True)
class UploadRecipeImage:
    session: AsyncSession
    compressor: ImageCompressor

    async def __call__(
        self,
        *,
        recipe_id: UUID,
        raw_bytes: bytes,
        mime: str,
    ) -> tuple[UUID, str, int]:
        """Compress to WebP, write to disk, update DB. Returns (recipe_id, image_url, size_kb)."""
        if mime not in _ALLOWED_MIMES:
            raise ValidationError(f"unsupported_mime:{mime}")
        if len(raw_bytes) > _MAX_BYTES:
            raise ValidationError(f"upload_too_large:{len(raw_bytes)}")

        row = (
            await self.session.execute(
                text("SELECT image_url FROM recipes WHERE id = :id"),
                {"id": str(recipe_id)},
            )
        ).first()
        if row is None:
            raise NotFoundError("recipe_not_found", recipe_id=str(recipe_id))

        old_url: str | None = row[0]

        compressed = await self.compressor.compress(raw_bytes, profile=CompressionProfile.RECIPE)

        sha = hashlib.sha256(compressed.bytes_).hexdigest()[:16]
        settings = get_settings()

        dest = Path(settings.recipe_image_dir) / str(recipe_id) / f"{sha}.webp"
        await asyncio.to_thread(_write_bytes, dest, compressed.bytes_)

        base_url = settings.recipe_image_base_url.rstrip("/")
        image_url = f"{base_url}/{recipe_id}/{sha}.webp"

        await self.session.execute(
            text("UPDATE recipes SET image_url = :url WHERE id = :id"),
            {"url": image_url, "id": str(recipe_id)},
        )

        # Delete old file only when it differs from the new one (same SHA = same file already written)
        if old_url and old_url != image_url:
            old_path = Path(settings.recipe_image_dir) / str(recipe_id) / Path(old_url).name
            await asyncio.to_thread(_delete_file_if_exists, old_path)

        return recipe_id, image_url, compressed.size_bytes // 1024
