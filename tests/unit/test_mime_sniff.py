"""Magic-byte MIME sniff tests (OWASP ASVS V12)."""

from __future__ import annotations

import pytest

from app.imaging.domain.mime_sniff import (
    assert_mime_matches,
    sniff_mime,
)


def test_sniff_jpeg():
    raw = b"\xff\xd8\xff\xe0" + b"\x00" * 20
    assert sniff_mime(raw) == "image/jpeg"


def test_sniff_png():
    raw = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
    assert sniff_mime(raw) == "image/png"


def test_sniff_webp():
    raw = b"RIFF" + b"\x00" * 4 + b"WEBP" + b"\x00" * 20
    assert sniff_mime(raw) == "image/webp"


def test_sniff_heic():
    raw = b"\x00\x00\x00\x20" + b"ftyp" + b"heic" + b"\x00" * 20
    assert sniff_mime(raw) == "image/heic"


def test_sniff_heif():
    raw = b"\x00\x00\x00\x20" + b"ftyp" + b"mif1" + b"\x00" * 20
    assert sniff_mime(raw) == "image/heif"


def test_sniff_too_short_returns_none():
    assert sniff_mime(b"\xff\xd8") is None


def test_sniff_unrecognised_returns_none():
    assert sniff_mime(b"<?php echo 1; ?>" + b"\x00" * 20) is None


def test_assert_mime_matches_jpeg_ok():
    raw = b"\xff\xd8\xff\xe0" + b"\x00" * 20
    assert assert_mime_matches(raw, "image/jpeg") == "image/jpeg"


def test_assert_mime_mismatch_raises():
    # PHP script with JPEG declared → mismatch
    raw = b"<?php echo 1; ?>" + b"\x00" * 20
    with pytest.raises(ValueError, match="mime_sniff_unrecognised"):
        assert_mime_matches(raw, "image/jpeg")


def test_assert_mime_jpeg_declared_png_actual_rejected():
    raw = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
    with pytest.raises(ValueError, match="mime_mismatch"):
        assert_mime_matches(raw, "image/jpeg")


def test_assert_mime_disguised_php_rejected():
    # Classic polyglot: HTML/PHP file with .jpg extension and image/jpeg Content-Type
    raw = b"GIF89a;<?php system($_GET['c']); ?>" + b"\x00" * 20
    with pytest.raises(ValueError):
        assert_mime_matches(raw, "image/jpeg")


def test_assert_mime_svg_rejected():
    # SVG can carry XSS; not in allowlist anyway
    raw = b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"
    with pytest.raises(ValueError):
        assert_mime_matches(raw, "image/jpeg")


def test_assert_mime_unsupported_declared_rejected():
    raw = b"\xff\xd8\xff\xe0" + b"\x00" * 20
    with pytest.raises(ValueError, match="unsupported_mime"):
        assert_mime_matches(raw, "image/gif")


def test_assert_mime_heic_heif_aliases_accepted():
    # heif brand declared as heic — both in family, accept
    raw = b"\x00\x00\x00\x20" + b"ftyp" + b"mif1" + b"\x00" * 20
    assert assert_mime_matches(raw, "image/heic") == "image/heif"
