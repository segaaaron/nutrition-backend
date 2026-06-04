# NOVA Nutrition — Arq worker container.
# Multi-stage build mirrors api.Dockerfile to avoid editable+hash pip conflict.

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

# Vision worker needs libvips + libheif for pyvips at runtime.
# libheif1 is a transitive dep of libvips42 on slim, kept explicit so
# `apt remove libvips42` cannot accidentally orphan HEIC decode support.
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

COPY app ./app
COPY worker ./worker
COPY pyproject.toml uv.lock* ./
COPY README.md ./

RUN pip install --no-cache-dir --no-deps .

USER 1000:1000

HEALTHCHECK --interval=60s --timeout=15s --start-period=20s --retries=3 \
  CMD python -c "import worker.main" || exit 1

CMD ["arq", "worker.main.WorkerSettings"]
