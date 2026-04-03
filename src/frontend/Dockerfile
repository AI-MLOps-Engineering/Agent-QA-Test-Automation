# src/frontend/Dockerfile
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PIP_NO_CACHE_DIR=1
WORKDIR /app

# dépendances système minimales (ffmpeg utile pour Gradio)
RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates ffmpeg gcc curl netcat-openbsd \
  && rm -rf /var/lib/apt/lists/*

# installer dépendances Python
COPY src/frontend/requirements.txt /app/requirements.txt
RUN pip install --upgrade pip setuptools wheel \
  && pip install --no-cache-dir -r /app/requirements.txt

# copier l'app
COPY src/frontend/ /app/

ENV API_BASE=http://api:8000
EXPOSE 7860

# lancer Gradio (assure server_name 0.0.0.0)
CMD ["python", "gradio_app.py"]