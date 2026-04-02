# src/api/Dockerfile
FROM python:3.11-slim

# Metadata
LABEL org.opencontainers.image.title="agent-qa-api"
LABEL org.opencontainers.image.description="API service for Agent QA & Test Automation"

ENV PYTHONUNBUFFERED=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl git ca-certificates \
  && rm -rf /var/lib/apt/lists/*

# Copy requirements if present (fallback to pip install)
# Expect a requirements.txt at project root or src/api/requirements.txt
COPY src/api/requirements.txt ./requirements.txt
RUN pip install --upgrade pip setuptools wheel \
  && pip install -r requirements.txt

# Copy application code
COPY src/api ./app

# Create upload/artifacts dirs and non-root user
RUN mkdir -p /data/uploads /data/artifacts \
  && groupadd -r app && useradd -r -g app app \
  && chown -R app:app /data

USER app
ENV UPLOAD_ROOT=/data/uploads \
    ARTIFACTS_ROOT=/data/artifacts \
    PYTHONPATH=/app

EXPOSE 8000

# Healthcheck uses the FastAPI health endpoint
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8000/api/health || exit 1

# Run with Uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
