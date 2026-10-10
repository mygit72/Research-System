# syntax=docker/dockerfile:1.7
# Backend image: used for both the API (uvicorn) and the Celery worker.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# tesseract: OCR fallback for scanned PDFs (used through PyMuPDF).
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*
ENV TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata

WORKDIR /app

# PyTorch wheel index: CPU by default (small image). For NVIDIA GPUs build with
#   docker compose build --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu124
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
RUN pip install torch --index-url ${TORCH_INDEX}

# Dependencies first for layer caching.
COPY backend/pyproject.toml ./
RUN mkdir app && touch app/__init__.py \
    && pip install ".[worker,ml]" \
    && rm -rf app

# Downloaded models (Hugging Face cache) live on a volume, so they're fetched once.
ENV HF_HOME=/app/models

COPY backend/ ./
RUN pip install --no-deps . \
    && useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/data /app/models && chown -R appuser /app/data /app/models
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# Apply migrations, then serve. (Workers override the command in compose.)
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
