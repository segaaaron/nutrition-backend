"""Imaging value objects."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CompressedImage:
    bytes_: bytes
    format: str  # 'webp' | 'avif'
    width: int
    height: int

    @property
    def size_bytes(self) -> int:
        return len(self.bytes_)
