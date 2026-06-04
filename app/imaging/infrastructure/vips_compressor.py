"""pyvips-based image compressor (libvips bindings).

Implements spec §10 including the mandatory EXIF-strip verification gate.
Fails closed via EXIFLeakError if any disallowed key survives the encode.

libvips is the same image-processing backend used by Sharp (Node.js) and
is the industry standard for high-throughput image pipelines: faster and
lower-memory than Pillow, with HEIC (iOS) + JPG/PNG/WEBP/AVIF (Android)
all handled by a single tool when libvips is compiled with libheif
(default on Debian-slim + Homebrew).

Trade-off vs Pillow: one system dep (libvips42 + libheif1, ~30-50 MB in
the Docker image) in exchange for one Python dep and a notably faster /
lower-memory hot path on the vision worker.
"""

from __future__ import annotations

import asyncio

import pyvips

from app.core.errors import EXIFLeakError
from app.imaging.domain.contracts import CompressionProfile, ImageCompressor
from app.imaging.domain.value_objects import CompressedImage

# Disallowed metadata fields (privacy-sensitive). libvips namespaces these
# under EXIF / GPS / XMP / IPTC families; ``Image.get_fields()`` exposes
# every surviving tag by name. We assert hard-fail on any presence.
#
# GPS IFD: ``exif-ifd3-*`` (libvips groups GPS sub-IFD under ifd3 in the
# default exif loader naming scheme).
_DISALLOWED_PREFIXES: tuple[str, ...] = (
    "exif-ifd3-",  # GPS IFD
    "gps-",
    "xmp",
    "iptc",
)
_DISALLOWED_EXACT: frozenset[str] = frozenset(
    {
        "exif-ifd0-Make",
        "exif-ifd0-Model",
        "exif-ifd0-Software",
        "exif-ifd2-DateTimeOriginal",
        "exif-ifd2-DateTimeDigitized",
    }
)

# Per-format libvips writer suffix (with options). ``strip`` drops EXIF /
# ICC / XMP / IPTC chunks at encode time; ``Q`` sets quality.
_VIPS_SUFFIX: dict[str, str] = {
    "webp": ".webp[Q={q},strip]",
    "avif": ".avif[Q={q},strip,compression=av1]",
}


def _assert_exif_stripped(out: bytes) -> None:
    """Raise EXIFLeakError if any privacy-sensitive metadata survived.

    Re-decodes the output bytes via libvips and inspects every field name
    on the resulting image; fails closed on any disallowed tag.
    """
    img = pyvips.Image.new_from_buffer(out, "", access="sequential")
    fields = img.get_fields()
    for name in fields:
        if name in _DISALLOWED_EXACT:
            raise EXIFLeakError(detail=f"Privacy-sensitive metadata survived: {name}")
        for prefix in _DISALLOWED_PREFIXES:
            if name.startswith(prefix):
                raise EXIFLeakError(detail=f"Privacy-sensitive metadata survived: {name}")


def _compress_sync(raw: bytes, profile: CompressionProfile) -> CompressedImage:
    fmt, q, max_dim = profile.value
    suffix = _VIPS_SUFFIX[fmt].format(q=q)

    # Sequential access streams pixels once → constant memory regardless of
    # input dimensions. Format is auto-detected from the buffer's magic bytes
    # (JPEG/PNG/WEBP/AVIF/HEIC all handled by the appropriate libvips loader).
    img = pyvips.Image.new_from_buffer(raw, "", access="sequential")

    # Bake EXIF orientation into pixel data (equivalent to PIL exif_transpose).
    img = img.autorot()

    # Resize preserving aspect ratio if any dimension exceeds the cap.
    w, h = img.width, img.height
    largest = max(w, h)
    if largest > max_dim:
        scale = max_dim / largest
        img = img.resize(scale)
        out_w = max(1, int(round(w * scale)))
        out_h = max(1, int(round(h * scale)))
    else:
        out_w, out_h = w, h

    # ``strip`` in the suffix already drops EXIF / ICC / XMP / IPTC, but
    # we also actively remove anything libvips may have re-derived from
    # the loader (e.g. orientation, iccp). Belt-and-braces for privacy.
    for field in img.get_fields():
        if field.startswith(("exif-", "xmp-", "iptc-", "icc-")) or field in (
            "orientation",
            "icc-profile-data",
        ):
            img.remove(field)

    out = img.write_to_buffer(suffix)

    _assert_exif_stripped(out)
    return CompressedImage(bytes_=out, format=fmt, width=out_w, height=out_h)


class VipsImageCompressor(ImageCompressor):
    async def compress(self, raw: bytes, *, profile: CompressionProfile) -> CompressedImage:
        # libvips releases the GIL during native work, but the Python wrapper
        # call itself is blocking; offload to a thread to keep the loop hot.
        return await asyncio.to_thread(_compress_sync, raw, profile)
