"""Shared pytest fixtures. Integration tests use testcontainers; unit tests
do not depend on this file's infrastructure fixtures.
"""
from __future__ import annotations

import pytest


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"
