"""Unit — C14: _handle_failure emits stable slugs, never raw class names."""

from __future__ import annotations

import pytest

from app.vision.application.process_vision_job import ProcessVisionJob


class _FakeExc(Exception):
    pass


class CostCapExceeded(Exception):
    pass


class ServiceUnavailable(Exception):
    pass


class RateLimited(Exception):
    pass


class UpstreamError(Exception):
    pass


class ImageUnreadable(Exception):
    pass


@pytest.mark.parametrize(
    "exc_class, expected_slug",
    [
        (CostCapExceeded, "vision_cost_cap"),
        (ServiceUnavailable, "vision_provider_unavailable"),
        (RateLimited, "vision_provider_unavailable"),
        (UpstreamError, "vision_provider_unavailable"),
        (TimeoutError, "vision_timeout"),
        (ImageUnreadable, "vision_image_unreadable"),
        (_FakeExc, "vision_internal"),
        (ValueError, "vision_internal"),
    ],
)
def test_slug_mapping(exc_class, expected_slug):
    slug = ProcessVisionJob._SLUG.get(exc_class.__name__, "vision_internal")
    assert slug == expected_slug


def test_asyncio_timeout_covered_by_timeout_error():
    import asyncio
    # asyncio.TimeoutError is TimeoutError in Py3.12; same __name__.
    slug = ProcessVisionJob._SLUG.get(asyncio.TimeoutError.__name__, "vision_internal")
    assert slug == "vision_timeout"


def test_no_raw_class_name_leaks():
    """No entry in _SLUG should be a Python class name path (e.g. 'asyncio.X')."""
    for key in ProcessVisionJob._SLUG:
        assert "." not in key, f"Key '{key}' looks like a module path — use __name__ only"
