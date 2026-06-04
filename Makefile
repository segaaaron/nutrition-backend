# NOVA Nutrition — Developer Shortcuts
#
# All commands assume .venv/bin python active. Use `make help` to list.
# Owner-only commands tagged [OWNER]. AI assistants must not run those.

.DEFAULT_GOAL := help
SHELL := /bin/bash
PY := .venv/bin/python
ALEMBIC := $(PY) -m alembic

# -- DB / Migrations -----------------------------------------------------------

.PHONY: db.new db.upgrade db.downgrade db.history db.current db.check db.help

db.new: ## Generate new migration. Usage: make db.new name="add_xyz_table"
	@if [ -z "$(name)" ]; then \
		echo "ERROR: pass name. Example: make db.new name=add_xyz_table"; \
		exit 1; \
	fi
	$(ALEMBIC) revision --autogenerate -m "$(name)"
	@echo ""
	@echo "Migration created. Review it under migrations/versions/ before applying."

db.upgrade: ## Apply all pending migrations (alembic upgrade head)
	$(ALEMBIC) upgrade head

db.downgrade: ## Rollback last migration (DESTRUCTIVE — be sure)
	@echo "WARNING: rolling back last migration. Press Ctrl+C to cancel."
	@sleep 3
	$(ALEMBIC) downgrade -1

db.history: ## Show migration history
	$(ALEMBIC) history --verbose

db.current: ## Show current DB revision
	$(ALEMBIC) current

db.check: ## Show pending migrations without applying them
	@echo "Pending migrations (not yet applied):"
	@$(ALEMBIC) heads
	@echo ""
	@echo "Current applied:"
	@$(ALEMBIC) current
	@echo ""
	@echo "If 'heads' != 'current' you have pending migrations."

db.help: ## DB workflow guide
	@echo ""
	@echo "DB Schema Change Workflow (recommended):"
	@echo ""
	@echo "  1. Edit SQLAlchemy models in app/<context>/infrastructure/models.py"
	@echo "  2. make db.new name=descriptive_name"
	@echo "  3. Open the generated migration in migrations/versions/ and REVIEW"
	@echo "     (autogenerate can miss enum changes, index types, constraints)"
	@echo "  4. make db.upgrade   # apply locally to dev DB"
	@echo "  5. Test against the new schema"
	@echo "  6. Commit migration file with the code change"
	@echo "  7. Push -> Dokploy deploys -> container entrypoint auto-runs"
	@echo "     alembic upgrade head before the API starts"
	@echo ""
	@echo "Rollback (dev only):     make db.downgrade"
	@echo "Inspect current:         make db.current"
	@echo "List all:                make db.history"
	@echo "Check pending:           make db.check"
	@echo ""

# -- Tests ---------------------------------------------------------------------

.PHONY: test test.unit test.vision test.cov

test: ## Run full test suite
	$(PY) -m pytest

test.unit: ## Run only unit tests
	$(PY) -m pytest tests/unit/ -v

test.vision: ## Run vision tests
	$(PY) -m pytest tests/unit/vision/ -v

test.cov: ## Run tests with coverage report
	$(PY) -m pytest --cov=app --cov-report=term-missing

integration: ## Run integration suite (testcontainers/Docker required). See docs/dev/RUNNING_INTEGRATION_TESTS.md
	@command -v docker >/dev/null 2>&1 || { echo "ERROR: docker daemon required for integration suite"; exit 1; }
	$(PY) -m pytest tests/integration -m integration --run-integration -v

# -- Perf baselines (k6 harness) -----------------------------------------------

.PHONY: perf-baseline load-smoke load-steady load-spike

perf-baseline: ## Run k6 baseline against local stack and emit JSON. See docs/perf/BASELINES.md.
	@command -v k6 >/dev/null 2>&1 || { echo "ERROR: install k6 (https://k6.io) for perf baseline"; exit 1; }
	@mkdir -p tests/load/results
	BASE_URL=$${BASE_URL:-http://localhost:8000} \
		k6 run --summary-export=tests/load/results/baseline_$$(date +%Y%m%d_%H%M%S).json \
		tests/load/k6_baseline.js

load-smoke: ## k6 smoke (5 RPS / 30s). See tests/load/README.md
	@command -v k6 >/dev/null 2>&1 || { echo "ERROR: install k6 (https://k6.io)"; exit 1; }
	k6 run -e BASE_URL=$${BASE_URL:-http://localhost:8000} -e TOKEN=$${TOKEN:-} \
		tests/load/k6_baseline_smoke.js

load-steady: ## k6 steady (100 RPS / 10 min). See tests/load/README.md
	@command -v k6 >/dev/null 2>&1 || { echo "ERROR: install k6 (https://k6.io)"; exit 1; }
	k6 run -e BASE_URL=$${BASE_URL:-http://localhost:8000} -e TOKEN=$${TOKEN:-} \
		tests/load/k6_steady_100rps_10m.js

load-spike: ## k6 spike (0→500 RPS / 30s). See tests/load/README.md
	@command -v k6 >/dev/null 2>&1 || { echo "ERROR: install k6 (https://k6.io)"; exit 1; }
	k6 run -e BASE_URL=$${BASE_URL:-http://localhost:8000} -e TOKEN=$${TOKEN:-} \
		tests/load/k6_spike_500rps_30s.js

# -- Catalog -------------------------------------------------------------------

.PHONY: catalog-audit

catalog-audit: ## Audit recipe catalog NULL ratio on R6 critical columns
	$(PY) -m scripts.catalog_completeness_audit

# -- Quality -------------------------------------------------------------------

.PHONY: lint typecheck format check

lint: ## Run ruff
	$(PY) -m ruff check app/ tests/

typecheck: ## Run mypy strict
	$(PY) -m mypy app/ --strict

format: ## Auto-format with ruff
	$(PY) -m ruff format app/ tests/
	$(PY) -m ruff check app/ tests/ --fix

check: lint typecheck pii-audit ## Run lint + typecheck + PII log audit

.PHONY: pii-audit

pii-audit: ## D8 — fail if INFO/WARN log lines under app/ contain PII tokens
	$(PY) -m scripts.pii_log_grep app/

# -- App -----------------------------------------------------------------------

.PHONY: run worker

run: ## Run API locally
	$(PY) -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

worker: ## Run Arq worker locally
	$(PY) -m arq worker.main.WorkerSettings

# -- Docker --------------------------------------------------------------------

.PHONY: docker.build docker.up docker.down docker.logs

docker.build: ## Build all containers
	docker-compose build

docker.up: ## Start docker-compose stack
	docker-compose up -d

docker.down: ## Stop docker-compose stack
	docker-compose down

docker.logs: ## Tail container logs
	docker-compose logs -f api

# -- Help ----------------------------------------------------------------------

.PHONY: help

help: ## Show this help
	@echo ""
	@echo "NOVA Nutrition — Available commands:"
	@echo ""
	@grep -E '^[a-zA-Z_.-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "For DB workflow help:   make db.help"
	@echo ""
