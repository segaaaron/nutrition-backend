"""Magic-byte MIME sniffing (OWASP ASVS V12 — Files/Resources).

Verifies declared Content-Type matches actual file bytes. Prevents
polyglot/disguised uploads (e.g. PHP script renamed .jpg, SVG with
embedded XSS, executable disguised as image).

Hardcoded magic-byte signatures for the 5 image formats NOVA accepts.
No external system dependency (no libmagic / file(1) required).
"""

from __future__ import annotations

JPEG_MAGIC = b"\xff\xd8\xff"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
WEBP_RIFF = b"RIFF"
WEBP_WEBP = b"WEBP"
HEIF_BRANDS = {b"heic", b"heix", b"heim", b"heis", b"hevc", b"hevx", b"mif1", b"msf1", b"heif"}

ALLOWED_MIME_TYPES: frozenset[str] = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/heic",
        "image/heif",
        "image/webp",
    }
)


def sniff_mime(raw: bytes) -> str | None:
    """Return canonical MIME type from magic bytes, or None if unrecognised."""
    if len(raw) < 12:
        return None

    if raw[:3] == JPEG_MAGIC:
        return "image/jpeg"

    if raw[:8] == PNG_MAGIC:
        return "image/png"

    # WebP: "RIFF" .... "WEBP"
    if raw[:4] == WEBP_RIFF and raw[8:12] == WEBP_WEBP:
        return "image/webp"

    # HEIF/HEIC: "....ftypBRAND" with BRAND at offset 8-12
    if len(raw) >= 12 and raw[4:8] == b"ftyp":
        brand = raw[8:12].lower()
        if brand in HEIF_BRANDS:
            # heif / heic are separate MIME types; brand bytes "heic"/"heix" → heic
            if brand in (b"heic", b"heix", b"hevc", b"hevx"):
                return "image/heic"
            return "image/heif"

    return None


def assert_mime_matches(raw: bytes, declared_mime: str) -> str:
    """Sniff actual MIME and verify against declared.

    Returns the canonical MIME on match. Raises ValueError on mismatch
    or unrecognised bytes.

    Used by SubmitPhoto to defend against polyglot uploads where
    Content-Type lies about the body.
    """
    if declared_mime not in ALLOWED_MIME_TYPES:
        raise ValueError(f"unsupported_mime:{declared_mime}")

    actual = sniff_mime(raw)
    if actual is None:
        raise ValueError("mime_sniff_unrecognised")

    # HEIC/HEIF aliasing — accept either direction if declared in that family.
    heif_family = {"image/heic", "image/heif"}
    if declared_mime in heif_family and actual in heif_family:
        return actual

    if actual != declared_mime:
        raise ValueError(f"mime_mismatch:declared={declared_mime}:actual={actual}")

    return actual
