"""FastAPI application factory. Swagger UI: /docs  -  ReDoc: /redoc"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.middleware import RequestContextMiddleware
from app.db.mongo import close_client
from app.db.mysql import dispose_engine
from app.logging_config import configure_logging
from app.routers import academic, admin, attendance, auth, join, reports, signup, students, workflow, ws
from app.services import face_service
from app.services.bootstrap import run_startup
from app.services.privacy import recover_sagas
from app.services.scheduler import start_scheduler, stop_scheduler
from app.ws.manager import live_manager

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger("app")

DESCRIPTION = """
Polyglot attendance system for **VIT Pune - DBMS project**.

* **MySQL 8** (ACID) - students, courses, sessions, attendance, users, audit log, overrides, saga log
* **MongoDB 7** (BASE) - encrypted face embeddings, recognition logs, snapshots, notifications, spoof attempts
* **InsightFace buffalo_l** (ArcFace 512-d) + liveness (blink / head turn)

Authenticate with **POST /auth/login** (or the *Authorize* button): staff use their e-mail, students their PRN.
"""

TAGS = [
    {"name": "auth", "description": "JWT authentication (bcrypt hashed passwords, lockout after failures)"},
    {"name": "students", "description": "Registration saga, face photos, bulk import, delete / forget-me"},
    {"name": "attendance", "description": "Group photo, late entry, QR fallback and reports"},
    {"name": "academic", "description": "Courses, teachers, sessions (time window), QR codes"},
    {"name": "join", "description": "Class codes: students scan a course QR to join (and sign up with their face)"},
    {"name": "signup", "description": "Public self sign-up from the login page (admin approval required)"},
    {"name": "workflow", "description": "Manual overrides, low-confidence review queue, notifications"},
    {"name": "reports", "description": "CSV / Excel / PDF exports and analytics"},
    {"name": "admin", "description": "Health, jobs, saga log, audit trail"},
]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    live_manager.bind_loop(asyncio.get_running_loop())
    status = await run_in_threadpool(run_startup)
    if not settings.testing:
        face_service.start_engine_loading(background=True)
        if status["mysql"] and status["mongo"]:
            try:
                await run_in_threadpool(recover_sagas, 1)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Initial saga recovery skipped: %s", exc)
        start_scheduler()
    logger.info("%s v%s started (env=%s)", settings.app_name, settings.app_version, settings.app_env)
    yield
    stop_scheduler()
    close_client()
    dispose_engine()


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, version=settings.app_version, description=DESCRIPTION,
                  openapi_tags=TAGS, lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    for module in (auth, signup, students, attendance, academic, join, workflow, reports, admin, ws):
        app.include_router(module.router)
    return app


app = create_app()
