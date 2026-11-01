"""Face engine lifecycle + vector-index synchronisation.

The engine loads in a background thread (model download can take minutes on
the very first boot); endpoints that need it answer 503 until it is ready.
The in-memory vector index is rebuilt whenever the Mongo `meta` version
counter changes, so several workers / restarts stay coherent.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

import numpy as np
from pymongo.errors import PyMongoError

from app.config import get_settings
from app.core.errors import AppError
from app.face.engines import create_engine
from app.face.matcher import EmbeddingIndex
from app.face.types import DetectedFace, FaceEngine
from app.repositories import embeddings as emb_repo

logger = logging.getLogger(__name__)


class _EngineHolder:
    def __init__(self) -> None:
        self.engine: FaceEngine | None = None
        self.status = "not_loaded"
        self.error: str | None = None
        self.loaded_at: float | None = None
        self._lock = threading.Lock()

    def load(self) -> None:
        with self._lock:
            if self.engine is not None or self.status == "loading":
                return
            self.status = "loading"
        s = get_settings()
        started = time.perf_counter()
        try:
            engine = create_engine(s.face_engine, s.insightface_model, s.insightface_root, s.det_size)
            with self._lock:
                self.engine, self.status, self.error = engine, "ready", None
                self.loaded_at = time.time()
            logger.info("Face engine '%s' ready in %.1fs", engine.name, time.perf_counter() - started)
            try:
                refresh_index(force=True)
            except Exception as exc:  # noqa: BLE001 - index loads lazily later
                logger.warning("Initial index load deferred: %s", exc)
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self.status, self.error = "failed", str(exc)
            logger.error("Face engine failed to load: %s", exc)

    def set(self, engine: FaceEngine) -> None:
        with self._lock:
            self.engine, self.status, self.error = engine, "ready", None


_holder = _EngineHolder()
_index = EmbeddingIndex(backend=get_settings().vector_backend)
_index_lock = threading.Lock()


def start_engine_loading(background: bool = True) -> None:
    if background:
        threading.Thread(target=_holder.load, name="face-engine-loader", daemon=True).start()
    else:
        _holder.load()


def set_engine(engine: FaceEngine) -> None:
    """Inject an engine (used by tests)."""
    _holder.set(engine)
    global _index
    _index = EmbeddingIndex(backend=get_settings().vector_backend)


def get_engine() -> FaceEngine:
    if _holder.engine is None:
        if _holder.status == "failed":
            raise AppError(503, "FACE_ENGINE_FAILED", f"Face engine failed to load: {_holder.error}")
        if _holder.status == "not_loaded":
            start_engine_loading(background=True)
        raise AppError(503, "FACE_ENGINE_LOADING", "Face engine is still loading, please retry in a moment")
    return _holder.engine


def engine_status() -> dict[str, Any]:
    info: dict[str, Any] = {"status": _holder.status, "error": _holder.error}
    if _holder.engine is not None:
        info.update(_holder.engine.describe())
        info["threshold"] = match_threshold()
        info["duplicate_threshold"] = duplicate_threshold()
    info["index"] = {"embeddings": _index.size, "students": _index.student_count, "version": _index.version,
                     "backend": _index.backend}
    return info


def match_threshold() -> float:
    s = get_settings()
    engine = _holder.engine
    # MATCH_THRESHOLD is tuned for ArcFace; other engines honour it only when chosen explicitly via FACE_ENGINE
    if s.match_threshold is not None and (engine is None or engine.name in ("insightface", "arcface_onnx", "fake")
                                          or engine.name == s.face_engine.lower()):
        return float(s.match_threshold)
    return float(engine.default_threshold if engine else (s.match_threshold or 0.45))


def duplicate_threshold() -> float:
    s = get_settings()
    if s.duplicate_threshold is not None:
        return float(s.duplicate_threshold)
    engine = _holder.engine
    return float(engine.default_duplicate_threshold if engine else 0.60)


def quality_thresholds(group: bool = False) -> dict[str, float]:
    s = get_settings()
    return {
        "min_face_px": s.group_min_face_px if group else s.min_face_px,
        "blur_threshold": s.blur_threshold * (0.5 if group else 1.0),
        "brightness_min": s.brightness_min,
        "brightness_max": s.brightness_max,
        "min_det_score": s.min_det_score,
    }


def detect(image_bgr: np.ndarray, max_faces: int = 0) -> list[DetectedFace]:
    return get_engine().detect(image_bgr, max_faces=max_faces)


def get_index() -> EmbeddingIndex:
    return _index


def refresh_index(force: bool = False) -> EmbeddingIndex:
    """Reload the in-memory index if MongoDB says it is stale."""
    engine = get_engine()
    try:
        version = emb_repo.get_index_version()
    except PyMongoError as exc:
        if _index.size or _index.version >= 0:
            logger.warning("MongoDB unreachable, using cached vector index v%s: %s", _index.version, exc)
            return _index
        raise
    if force or version != _index.version or _index.model != engine.model_id:
        with _index_lock:
            if force or version != _index.version or _index.model != engine.model_id:
                items = emb_repo.load_active(engine.model_id)
                _index.build(items, version, engine.model_id)
    return _index


def notify_embeddings_changed() -> None:
    """Bump the shared version so every worker reloads, then reload here."""
    try:
        emb_repo.bump_index_version()
    finally:
        try:
            refresh_index(force=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Index refresh after change failed: %s", exc)
