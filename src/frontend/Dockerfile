# src/frontend/Dockerfile
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl ca-certificates \
  && rm -rf /var/lib/apt/lists/*

COPY src/frontend/requirements.txt ./requirements.txt
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY src/frontend ./frontend

EXPOSE 7860

# Healthcheck: simple HTTP check to Gradio root (may be proxied)
HEALTHCHECK --interval=20s --timeout=3s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:7860/ || exit 1

CMD ["python", "frontend/gradio_app.py"]
