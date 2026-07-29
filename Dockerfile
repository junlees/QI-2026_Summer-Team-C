# syntax=docker/dockerfile:1
#
# AgriSage container for Google Cloud Run.
# Multi-stage: (1) a Node stage builds the Tailwind CSS, (2) a Python stage
# installs CPU-only torch + the backend deps and copies the built frontend in.
# Cloud Run injects $PORT (8080); gunicorn binds to it.

# --- Stage 1: build the Tailwind CSS -----------------------------------------
FROM node:20-slim AS frontend-build
WORKDIR /app/frontend
# Install deps first (cached until the lockfile changes), then build.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build      # -> /app/frontend/css/styles.css

# --- Stage 2: Python runtime --------------------------------------------------
FROM python:3.12-slim AS app

# OMP_NUM_THREADS: torch sizes its thread pool from the *host* core count, which
# on Cloud Run is far higher than the container's vCPU limit — left unset it
# oversubscribes and both slows inference down and inflates memory. 2 matches the
# recommended 2-vCPU service setting.
# ALLOW_EPHEMERAL_SQLITE makes this image self-contained for disposable demos.
# Set it to false and provide DATABASE_URL to use persistent PostgreSQL instead.
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8080 \
    OMP_NUM_THREADS=2 \
    MKL_NUM_THREADS=2 \
    ALLOW_EPHEMERAL_SQLITE=true \
    EPHEMERAL_SQLITE_PATH=/tmp/agrisage-demo.db \
    MODEL_CHECKPOINT_PATH=backend/models/weights/classification_model.pth \
    MODEL_CONFIG_PATH=backend/models/config6.json

# opencv-python-headless needs libglib2.0-0; torch/numpy need libgomp1.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CPU-only torch wheels FIRST — the default PyPI wheel bundles CUDA and is far
# too large for the image. requirements' torch==2.9.1 is then already satisfied
# by 2.9.1+cpu and is not re-downloaded.
RUN pip install --upgrade pip \
    && pip install torch==2.9.1 torchvision==0.24.1 --index-url https://download.pytorch.org/whl/cpu

COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt

# App code: backend (incl. the committed model weights/config) + the static
# frontend, with only the built CSS pulled from the Node stage.
COPY backend/ backend/
COPY frontend/ frontend/
COPY --from=frontend-build /app/frontend/css/styles.css frontend/css/styles.css

EXPOSE 8080
# exec so gunicorn replaces the shell and receives Cloud Run's SIGTERM directly.
# workers 1 (the torch model must not be loaded once per process on a 2Gi
# instance) + threads 4, so requests parked on an OpenAI call don't block the
# rest — a single sync worker would serialize every concurrent diagnosis.
CMD ["sh", "-c", "exec gunicorn --chdir backend --workers 1 --threads 4 --timeout 120 --bind 0.0.0.0:${PORT:-8080} app:app"]
