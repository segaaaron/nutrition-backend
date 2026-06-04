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

import pytest


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
