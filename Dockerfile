# ---------------------------------------------------------------------------
#  Single-service image for Render (or any container host):
#  FastAPI + ArcFace ONNX models + the built React app, served by app.serve.
#  MySQL and MongoDB are external (MYSQL_HOST / MONGO_URI), see render.yaml.
#  docker compose keeps using backend/Dockerfile + frontend/Dockerfile.
# ---------------------------------------------------------------------------

# ---- 1. build the React app ----
FROM node:20-alpine AS frontend
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- 2. ArcFace ONNX models (insightface release, no insightface package needed) ----
FROM python:3.12-slim AS models
ARG INSIGHTFACE_MODEL=buffalo_s
COPY backend/scripts/fetch_arcface.py /tmp/fetch_arcface.py
RUN python /tmp/fetch_arcface.py ${INSIGHTFACE_MODEL} /models

# ---- 3. runtime ----
FROM python:3.12-slim
ARG INSIGHTFACE_MODEL=buffalo_s
ENV INSIGHTFACE_MODEL=${INSIGHTFACE_MODEL} \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MPLCONFIGDIR=/tmp/matplotlib \
    TZ=Asia/Kolkata \
    INSIGHTFACE_ROOT=/models \
    FRONTEND_DIST=/app/static \
    DATA_DIR=/app/data \
    FACE_ENGINE=arcface_onnx

RUN apt-get update \
 && apt-get install -y --no-install-recommends libglib2.0-0 libgomp1 tzdata \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt onnxruntime==1.20.1

COPY backend/app ./app
COPY --from=models /models /models
COPY --from=frontend /src/dist ./static

RUN useradd --create-home --uid 1000 appuser && mkdir -p /app/data && chown -R appuser:appuser /app
USER appuser

# Render injects PORT; one worker: the scheduler and the in-memory face index live in-process
CMD ["sh", "-c", "uvicorn app.serve:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers --forwarded-allow-ips '*'"]
