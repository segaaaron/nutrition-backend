"""Shared pytest fixtures. Integration tests use testcontainers; unit tests
do not depend on this file's infrastructure fixtures.

Integration gating (D4, Sprint 3):
- ``--run-integration`` CLI flag opts in to integration suites that need
  Docker / Postgres / Redis / OpenAI key.
- The ``integration`` marker (declared in ``pyproject.toml``) is applied
  module-wide in each integration test file. Tests carrying the marker are
  skipped unless ``--run-integration`` is passed OR the suite has its own
  environment gate (e.g. Docker daemon reachable).
"""

from __future__ import annotations

import os

import pytest

# Inject required env vars BEFORE any `app.core.config` import. Since
# DATABASE_URL is now a required Settings field with a fail-loud validator
# (no fallback default), every test that constructs Settings() needs it set.
# Tests that care about the specific value (e.g. integration suites using
# testcontainers) override it explicitly via monkeypatch / fixtures.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5432/test",
)
# Same fail-loud requirement now applies to REDIS_URL and the billing redirect
# URLs (hardcoded defaults removed 2026-06-04). Tests that exercise the real
# settings construction need these set; specific suites override as needed.
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("BILLING_SUCCESS_URL", "https://test.example/success")
os.environ.setdefault("BILLING_CANCEL_URL", "https://test.example/cancel")


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run tests marked with @pytest.mark.integration. "
        "Requires Docker daemon + docker-compose stack. "
        "See docs/dev/RUNNING_INTEGRATION_TESTS.md.",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip integration tests by default; opt in with --run-integration."""
    if config.getoption("--run-integration"):
        return
    skip_marker = pytest.mark.skip(
        reason="integration suite gated; pass --run-integration to enable"
    )
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_marker)


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def fake_redis():
    import fakeredis.aioredis

    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield client
    await client.aclose()


@pytest.fixture
def fake_redis_sync():
    """Async FakeRedis returned synchronously — for middleware tests using
    starlette TestClient which sync-drives async middleware via anyio."""
    import fakeredis.aioredis

    return fakeredis.aioredis.FakeRedis(decode_responses=True)
