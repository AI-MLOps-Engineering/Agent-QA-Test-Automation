# src/model/Dockerfile
FROM python:3.11-slim

WORKDIR /model

ENV PYTHONUNBUFFERED=1

# Minimal HTTP wrapper for a model server (placeholder)
COPY src/model/requirements.txt ./requirements.txt
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY src/model ./model

EXPOSE 5100

HEALTHCHECK --interval=20s --timeout=3s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:5100/health || exit 1

CMD ["python", "model/server.py"]
