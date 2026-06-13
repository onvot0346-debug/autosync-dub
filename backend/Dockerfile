# Multi-stage Dockerfile for the autosync-dub backend (FastAPI + Whisper + Demucs + Edge-TTS)
# Designed to run on Render / Railway / Fly.io / any Docker-friendly host.

FROM python:3.11-slim

# System packages
RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg libsndfile1 git \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install Python deps first (better Docker layer cache)
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy application
COPY . .

# Persistent storage path (configurable via STORAGE_DIR env)
ENV STORAGE_DIR=/var/data/dubbing
RUN mkdir -p /var/data/dubbing

EXPOSE 8001

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001"]
