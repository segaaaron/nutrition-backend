# NOVA Nutrition — API container (FastAPI + Uvicorn).
# Multi-stage build minimizes final image size.
# Includes data/ (catalog JSON) + scripts/ for seed runs via `docker exec`.

# --- Stage 1: builder ---
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY pyproject.toml uv.lock* ./

RUN pip install --no-cache-dir uv \
    && uv export --no-dev --frozen --no-emit-project --format requirements-txt > /tmp/requirements.txt \
    && pip install --prefix=/install --no-cache-dir -r /tmp/requirements.txt

# --- Stage 2: runtime ---
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    libvips42 \
    libheif1 \
    libpq5 \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install built dependencies from builder stage.
COPY --from=builder /install /usr/local

WORKDIR /app

# Application code, migrations, and seed/operation scripts.
# data/ is needed at runtime ONLY during seed (via `docker exec ... python -m scripts.seed_recipes`).
# Could move to a volume in production if image size becomes constrained.
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
COPY scripts ./scripts
COPY data ./data
COPY pyproject.toml uv.lock* ./
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh \
    && pip install --no-cache-dir --no-deps .

USER 1000:1000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD curl -fsS http://localhost:8000/healthz || exit 1

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
