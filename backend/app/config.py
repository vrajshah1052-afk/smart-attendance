"""Application settings (12-factor: everything comes from the environment).

Secrets that are not provided (JWT secret, embedding encryption key) are
generated once and persisted under DATA_DIR so restarts keep working while
nothing secret is ever hard-coded in the source tree.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from cryptography.fernet import Fernet
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app import __version__

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ----------------------------------------------------------- general
    app_name: str = "Smart Face Recognition Attendance System"
    app_version: str = __version__
    app_env: str = "development"
    log_level: str = "INFO"
    timezone: str = "Asia/Kolkata"
    data_dir: Path = Path("./data")
    cors_origins: str = "http://localhost:3000,http://localhost:5173"
    frontend_url: str = "http://localhost:3000"
    render_external_url: str = ""  # set by Render for web services (https://<name>.onrender.com)
    frontend_dist: str = ""  # built SPA served by app.serve (single-service deploy)
    testing: bool = False

    # ------------------------------------------------------------- MySQL
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_database: str = "attendance_db"
    mysql_app_user: str = "attendance_app"
    mysql_app_password: str = ""
    mysql_pool_size: int = 10
    mysql_ssl: bool = False  # managed MySQL (Aiven, ...) requires TLS
    mysql_ssl_ca: str = ""  # CA certificate: PEM text or a file path; empty = encrypt without verifying
    mysql_time_zone: str = ""  # per-connection time_zone (e.g. +05:30) when the server runs in UTC
    mysql_connect_retries: int = 30

    # ----------------------------------------------------------- MongoDB
    mongo_uri: str | None = None
    mongo_host: str = "localhost"
    mongo_port: int = 27017
    mongo_app_user: str = ""
    mongo_app_password: str = ""
    mongo_db: str = "attendance_logs"
    mongo_auth_db: str | None = None

    # ---------------------------------------------------------- security
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480
    embedding_enc_key: str = ""
    bcrypt_rounds: int = 12
    admin_email: str = "admin@example.org"
    admin_password: str = ""
    demo_user_password: str = ""
    login_max_failures: int = 5
    login_lock_minutes: int = 15

    # ------------------------------------------------------- face engine
    face_engine: str = "auto"  # auto | insightface | face_recognition | opencv
    insightface_model: str = "buffalo_l"
    insightface_root: str = "/models"
    det_size: int = 640
    face_threads: int = 0  # onnxruntime threads (0 = one per core); 1 on a fractional-CPU container
    face_low_memory: bool = False  # arcface_onnx: trade some speed for a lower memory peak (512 MB hosts)
    match_threshold: float | None = None
    duplicate_threshold: float | None = None
    low_conf_margin: float = 0.08
    reenroll_margin: float = 0.10
    auto_reenroll: bool = True
    max_embeddings_per_student: int = 15
    min_reg_photos: int = 5
    max_reg_photos: int = 10
    reg_min_yaw_range: float = 10.0
    blur_threshold: float = 30.0  # Laplacian variance on a 160px face; calibrated on real faces
    brightness_min: float = 50.0
    brightness_max: float = 210.0
    min_face_px: int = 80
    group_min_face_px: int = 28
    min_det_score: float = 0.55
    max_upload_mb: float = 8.0
    vector_backend: str = "auto"  # auto | numpy | faiss

    # ---------------------------------------------------------- liveness
    liveness_required: bool = True
    liveness_min_frames: int = 3
    liveness_max_frames: int = 15
    liveness_min_yaw_delta: float = 15.0
    liveness_ear_closed: float = 0.21
    liveness_ear_drop_ratio: float = 0.75
    liveness_static_diff: float = 1.2
    liveness_challenge_ttl: int = 120
    moire_threshold: float = 3.2
    glare_threshold: float = 0.30

    # -------------------------------------------------------- attendance
    shortage_threshold: float = 75.0
    session_window_enforced: bool = True
    session_open_early_min: int = 15
    auto_close_grace_min: int = 15
    qr_window_seconds: int = 30
    self_registration_enabled: bool = True  # new students may sign up from a course QR / class code

    # ------------------------------------------------- retention (TTL)
    recognition_log_ttl_days: int = 90
    snapshot_ttl_days: int = 30
    draft_ttl_hours: int = 12

    # ------------------------------------------------------------- email
    email_enabled: bool = True
    smtp_host: str = ""
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "Smart Attendance <no-reply@example.org>"
    smtp_starttls: bool = False
    smtp_ssl: bool = False

    # --------------------------------------------------------- scheduler
    scheduler_enabled: bool = True
    daily_summary_hour: int = 18
    shortage_alert_day: str = "mon"
    shortage_alert_hour: int = 9

    @field_validator("match_threshold", "duplicate_threshold", "mongo_uri", "mongo_auth_db", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

    # ---------------------------------------------------------- helpers
    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def public_url(self) -> str:
        """Base URL printed into QR codes: FRONTEND_URL if set, else the Render URL."""
        if "frontend_url" not in self.model_fields_set and self.render_external_url:
            return self.render_external_url.rstrip("/")
        return self.frontend_url.rstrip("/")

    @property
    def mongo_connection_uri(self) -> str:
        if self.mongo_uri:
            return self.mongo_uri
        if self.mongo_app_user:
            auth_db = self.mongo_auth_db or self.mongo_db.removesuffix("_test")
            return (
                f"mongodb://{quote_plus(self.mongo_app_user)}:{quote_plus(self.mongo_app_password)}"
                f"@{self.mongo_host}:{self.mongo_port}/?authSource={auth_db}"
            )
        return f"mongodb://{self.mongo_host}:{self.mongo_port}"

    @property
    def max_upload_bytes(self) -> int:
        return int(self.max_upload_mb * 1024 * 1024)


def _ensure_secrets(settings: Settings) -> None:
    """Fill JWT secret / Fernet key from DATA_DIR/secrets.json or generate them."""
    if settings.jwt_secret and settings.embedding_enc_key:
        return
    path = settings.data_dir / "secrets.json"
    stored: dict[str, str] = {}
    try:
        if path.exists():
            stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("Could not read %s: %s", path, exc)

    changed = False
    if not settings.jwt_secret:
        if not stored.get("jwt_secret"):
            stored["jwt_secret"] = secrets.token_urlsafe(48)
            changed = True
        settings.jwt_secret = stored["jwt_secret"]
    if not settings.embedding_enc_key:
        if not stored.get("embedding_enc_key"):
            stored["embedding_enc_key"] = Fernet.generate_key().decode()
            changed = True
        settings.embedding_enc_key = stored["embedding_enc_key"]

    if changed:
        try:
            settings.data_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(stored, indent=2), encoding="utf-8")
            os.chmod(path, 0o600)
            logger.warning("Generated missing secrets and stored them in %s (keep this volume safe!)", path)
        except OSError as exc:
            logger.error("Could not persist generated secrets (%s); they will change on restart", exc)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    _ensure_secrets(settings)
    return settings
