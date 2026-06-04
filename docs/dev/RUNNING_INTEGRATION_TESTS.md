# Running integration tests

Integration tests are gated. They never run in the default `make test` or `pytest`
invocation. Two reasons:

1. They boot Docker containers (Postgres 16 + pgvector, sometimes Redis).
2. Some need OpenAI API access and would burn cost-cap budget.

## Quick start

```bash
# 1. Ensure Docker daemon is running
docker info

# 2. Run integration suite
make integration

# Equivalent raw command:
.venv/bin/python -m pytest tests/integration -m integration --run-integration -v
```

## Gating mechanism (D4, Sprint 3)

| Layer | Mechanism | File |
|-------|-----------|------|
| CLI flag | `--run-integration` opts in | `tests/conftest.py::pytest_addoption` |
| Auto-skip | Tests marked `@pytest.mark.integration` are skipped without the flag | `tests/conftest.py::pytest_collection_modifyitems` |
| Docker probe | Vision suite probes `docker.from_env().ping()`; if Docker is down, the whole module is skipped even with the flag | `tests/integration/vision/conftest.py` |
| Perf gate | `tests/perf/` uses `RUN_PERF=1` env var (independent of integration) | `tests/perf/test_vector_recall.py` |

## Required environment

| Variable | Purpose | Default |
|----------|---------|---------|
| `DOCKER_HOST` | testcontainers socket | OS default |
| `TESTCONTAINERS_RYUK_DISABLED` | set to `true` if Ryuk reaper fails (e.g. colima, podman) | unset |
| `OPENAI_API_KEY` | only required by suites that hit OpenAI; otherwise harmless to omit | unset |
| `NOVA_DB_DSN` | overridden by testcontainers, leave unset | unset |

## What runs

- `tests/integration/vision/` — full vision pipeline against pgvector container.
- `tests/integration/test_plan_generation.py` — Layer1-4 happy path (placeholder).
- `tests/perf/` (separate; needs `RUN_PERF=1`) — vector recall sanity checks.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| All vision tests skipped | Docker daemon not reachable | `docker info`; restart Docker Desktop / colima |
| `port already allocated` | leftover testcontainer | `docker ps -a` then `docker rm -f` |
| `ryuk failed to start` | rootless / podman / colima quirk | `export TESTCONTAINERS_RYUK_DISABLED=true` |
| `alembic.command.upgrade` fails | container has 0011 partial-index from a previous run | the vision conftest manually skips `0011` because `CONCURRENTLY` needs no transaction; if a future migration adds the same trick, copy the same handling |

## Adding a new integration test

1. Place file under `tests/integration/<context>/`.
2. Top of file: `pytestmark = pytest.mark.integration`.
3. If the suite needs a fresh Docker probe, copy `tests/integration/vision/conftest.py::DOCKER_AVAILABLE`.
4. Do NOT spin Docker in `tests/unit/` — units must run without network or container deps.
