"""Admin: jobs, system status. Health & public config.

The audit trail and the saga log are still written (MySQL triggers and the saga
recorder); they just have no endpoint or screen any more.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query

from app.config import get_settings
from app.core.deps import CurrentUser, require_admin
from app.db.mongo import last_mongo_error, ping_mongo
from app.db.mysql import ping
from app.services import face_service
from app.services.scheduler import JOBS
from app.ws.manager import live_manager

router = APIRouter(tags=["admin"])


@router.get("/health/live", include_in_schema=False)
def live() -> dict:
    return {"status": "ok"}


@router.get("/health", summary="Readiness of MySQL, MongoDB and the face engine")
def health() -> dict:
    mysql_ok, mongo_ok = ping(), ping_mongo()
    engine = face_service.engine_status()
    status = "ok" if mysql_ok and mongo_ok and engine["status"] == "ready" else "degraded"
    return {"status": status, "mysql": mysql_ok, "mongo": mongo_ok,
            "mongo_error": None if mongo_ok else last_mongo_error(), "engine": engine,
            "websocket_clients": live_manager.client_count, "version": get_settings().app_version}


@router.get("/config/public", summary="Non-secret settings the UI needs")
def public_config() -> dict:
    s = get_settings()
    engine = face_service.engine_status()
    return {
        "min_photos": s.min_reg_photos, "max_photos": s.max_reg_photos,
        "match_threshold": face_service.match_threshold(), "low_conf_margin": s.low_conf_margin,
        "liveness_required": s.liveness_required, "shortage_threshold": s.shortage_threshold,
        "qr_window_seconds": s.qr_window_seconds, "engine": engine.get("name"), "engine_status": engine["status"],
        "max_upload_mb": s.max_upload_mb, "self_registration": s.self_registration_enabled,
    }


@router.post("/admin/jobs/{job}", summary="Run a background job now")
def run_job(job: Literal["auto_close_sessions", "recover_sagas", "daily_summary", "shortage_alerts"],
            _: CurrentUser = Depends(require_admin)) -> dict:
    result = JOBS[job]()
    return {"job": job, "result": result}


@router.post("/admin/index/reload", summary="Force reload of the in-memory vector index")
def reload_index(_: CurrentUser = Depends(require_admin)) -> dict:
    index = face_service.refresh_index(force=True)
    return {"embeddings": index.size, "students": index.student_count, "version": index.version,
            "backend": index.backend}
