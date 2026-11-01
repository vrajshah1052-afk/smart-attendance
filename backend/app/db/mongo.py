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
    try:
        get_db().command("ping")
        return True
    except PyMongoError:
        return False


def wait_for_mongo(retries: int, delay: float = 2.0) -> bool:
    for attempt in range(1, retries + 1):
        try:
            get_db().command("ping")
            logger.info("MongoDB reachable (attempt %d)", attempt)
            return True
        except PyMongoError as exc:  # say why: wrong password vs. IP not on the Atlas access list
            logger.warning("MongoDB not reachable yet (attempt %d/%d): %s", attempt, retries, str(exc)[:400])
        time.sleep(delay)
    return False


def close_client() -> None:
    global _client
    with _lock:
        if _client is not None:
            _client.close()
            _client = None
