"""MongoDB client (PyMongo, sync). Collections are referenced via `col()`."""
from __future__ import annotations

import logging
import threading
import time

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import PyMongoError

from app.config import get_settings

logger = logging.getLogger(__name__)

_client: MongoClient | None = None
_last_error: str | None = None  # why the last ping failed (bad auth, IP not allowed, bad URI)
_lock = threading.Lock()


class C:
    """Collection names (single source of truth)."""

    FACE_EMBEDDINGS = "face_embeddings"
    RECOGNITION_LOGS = "recognition_logs"
    SNAPSHOTS = "snapshots"
    NOTIFICATIONS = "notifications"
    SPOOF_ATTEMPTS = "spoof_attempts"
    REVIEW_QUEUE = "review_queue"
    ATTENDANCE_DRAFTS = "attendance_drafts"
    LIVENESS_NONCES = "liveness_nonces"
    META = "meta"


def get_client() -> MongoClient:
    global _client
    if _client is None:
        with _lock:
            if _client is None:
                _client = MongoClient(
                    get_settings().mongo_connection_uri,
                    serverSelectionTimeoutMS=3000,
                    connectTimeoutMS=3000,
                    socketTimeoutMS=20000,
                    tz_aware=True,
                    appname="smart-attendance",
                )
    return _client


def get_db() -> Database:
    return get_client()[get_settings().mongo_db]


def col(name: str) -> Collection:
    return get_db()[name]


def ping_mongo() -> bool:
    global _last_error
    try:
        get_db().command("ping")
        _last_error = None
        return True
    except PyMongoError as exc:  # driver messages name hosts, never the password
        _last_error = f"{type(exc).__name__}: {str(exc)[:300]}"
        return False


def last_mongo_error() -> str | None:
    return _last_error


def wait_for_mongo(retries: int, delay: float = 2.0) -> bool:
    for attempt in range(1, retries + 1):
        if ping_mongo():
            logger.info("MongoDB reachable (attempt %d)", attempt)
            return True
        logger.warning("MongoDB not reachable yet (attempt %d/%d): %s", attempt, retries, _last_error)
        time.sleep(delay)
    return False


def close_client() -> None:
    global _client
    with _lock:
        if _client is not None:
            _client.close()
            _client = None
