# ---------------------------------------------------------------------------
#  FastAPI backend - Python 3.11, InsightFace (CPU / onnxruntime)
# ---------------------------------------------------------------------------
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    INSIGHTFACE_ROOT=/models \
    MPLCONFIGDIR=/tmp/matplotlib \
    NO_ALBUMENTATIONS_UPDATE=1 \
    TZ=Asia/Kolkata

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential g++ libglib2.0-0 libgl1 libgomp1 curl tzdata \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 1) numeric base + Cython (needed to compile insightface's mesh extension).
#    constraints.txt pins numpy 1.26 for EVERY later pip call (ABI of the extension)
COPY constraints.txt ./
ENV PIP_CONSTRAINT=/app/constraints.txt
RUN pip install setuptools==75.6.0 wheel==0.45.1 numpy==1.26.4 Cython==3.0.11

# 2) python dependencies (cached layer)
COPY requirements.txt requirements-face.txt requirements-dev.txt ./
RUN pip install --no-build-isolation -r requirements.txt -r requirements-face.txt -r requirements-dev.txt \
 && python -c "import numpy, insightface.app; assert numpy.__version__.startswith('1.26'), numpy.__version__"

# 3) optional dlib / face_recognition fallback engine (slow to compile)
ARG INSTALL_DLIB=false
RUN if [ "$INSTALL_DLIB" = "true" ]; then \
      apt-get update && apt-get install -y --no-install-recommends cmake && rm -rf /var/lib/apt/lists/* && \
      pip install dlib==19.24.6 face_recognition==1.3.0 ; \
    fi

# 4) application code
COPY . .

# 5) pre-download InsightFace buffalo_l so the first start is fast (non fatal)
ARG PRELOAD_MODELS=true
RUN mkdir -p /models /app/data /app/benchmarks \
 && if [ "$PRELOAD_MODELS" = "true" ]; then \
      python -m scripts.preload_models || echo "WARNING: model preload failed, will download at runtime"; \
    fi

# run as an unprivileged user
RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app /models
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=20 \
  CMD curl -fsS http://localhost:8000/health/live || exit 1

# single worker: the APScheduler jobs and the in-memory vector index live in-process
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
