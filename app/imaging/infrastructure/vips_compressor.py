"""pyvips + pillow-heif image compressor.

Implements spec §10 including the mandatory EXIF-strip verification gate.
Fails closed via EXIFLeakError if any disallowed key survives the
`write_to_buffer(..., strip)` call.
"""

from __future__ import annotations

import asyncio
import io

import exifread
import pillow_heif
import pyvips

from app.core.errors import EXIFLeakError
from app.imaging.domain.contracts import CompressionProfile, ImageCompressor
from app.imaging.domain.value_objects import CompressedImage

pillow_heif.register_heif_opener()

_DISALLOWED_PREFIXES = ("GPS",)
_DISALLOWED_TAGS = frozenset(
    {
        "Image Make",
        "Image Model",
        "Image Software",
        "EXIF DateTimeOriginal",
        "EXIF DateTimeDigitized",
    }
)


def _assert_exif_stripped(out: bytes) -> None:
    """Raise EXIFLeakError if any privacy-sensitive EXIF tag survived."""
    tags = exifread.process_file(io.BytesIO(out), details=False)
    for key in tags:
        if any(key.startswith(p) for p in _DISALLOWED_PREFIXES):
            raise EXIFLeakError(detail=f"GPS EXIF tag survived: {key}")
        if key in _DISALLOWED_TAGS:
            raise EXIFLeakError(detail=f"Privacy-sensitive EXIF tag survived: {key}")


def _compress_sync(raw: bytes, profile: CompressionProfile) -> CompressedImage:
    fmt, q, max_dim = profile.value
    img = pyvips.Image.new_from_buffer(raw, "", access="sequential")
    img = img.autorot()
    for f in img.get_fields():
        if f.startswith("exif-"):
            img.remove(f)
    scale = min(1.0, max_dim / max(img.width, img.height))
    if scale < 1.0:
        img = img.resize(scale)
    out: bytes = img.write_to_buffer(f".{fmt}[Q={q},strip]")
    _assert_exif_stripped(out)
    return CompressedImage(bytes_=out, format=fmt, width=img.width, height=img.height)


class VipsImageCompressor(ImageCompressor):
    async def compress(self, raw: bytes, *, profile: CompressionProfile) -> CompressedImage:
        # pyvips is C-bound and blocking; offload to a thread.
        return await asyncio.to_thread(_compress_sync, raw, profile)
