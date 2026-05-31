"""Imaging domain port: ImageCompressor protocol + CompressionProfile enum."""
from __future__ import annotations

from enum import Enum
from typing import Protocol


class CompressionProfile(Enum):
    MEAL_PHOTO = ("webp", 82, 1024)
    PROGRESS = ("avif", 60, 1600)
    THUMBNAIL = ("webp", 70, 400)
    AVATAR = ("webp", 80, 512)


class ImageCompressor(Protocol):
    async def compress(
        self, raw: bytes, *, profile: CompressionProfile
    ) -> "CompressedImage":  # noqa: F821 — forward ref
        ...
