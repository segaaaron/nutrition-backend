FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Vision worker needs libvips + libheif for pyvips/pillow-heif at runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libvips42 \
    libheif1 \
    libpq5 \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml uv.lock* ./

RUN pip install --no-cache-dir uv \
    && uv sync --frozen --no-dev 2>/dev/null \
       || uv pip install --system -r <(uv pip compile pyproject.toml 2>/dev/null) \
       || pip install --no-cache-dir .

COPY app ./app
COPY worker ./worker

USER 1000:1000

HEALTHCHECK --interval=60s --timeout=15s --start-period=20s --retries=3 \
  CMD python -c "import worker.main" || exit 1

CMD ["arq", "worker.main.WorkerSettings"]
