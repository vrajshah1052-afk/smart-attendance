"""MongoDB: recognition logs, snapshots, attendance drafts + aggregation pipelines."""
from __future__ import annotations

import datetime as dt
import logging
import threading
from typing import Any

from bson import Binary, ObjectId
from bson.errors import InvalidId
from pymongo import DESCENDING, ReturnDocument
from pymongo.errors import PyMongoError

from app.config import get_settings
from app.core.utils import to_builtin, utcnow
from app.db.mongo import C, col

logger = logging.getLogger(__name__)


def _oid(value: str) -> ObjectId | None:
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return None


# ---------------------------------------------------------------- recognition logs
def log_recognitions(entries: list[dict[str, Any]]) -> None:
    """Best effort (BASE): a Mongo outage must never block attendance."""
    if not entries:
        return
    now = utcnow()
    docs = [{**to_builtin(e), "created_at": now} for e in entries]
    try:
        col(C.RECOGNITION_LOGS).insert_many(docs, ordered=False)
    except PyMongoError as exc:
        logger.warning("recognition_logs write skipped: %s", exc)


def recent_confidences(prn: str, limit: int = 5) -> list[float]:
    cursor = col(C.RECOGNITION_LOGS).find(
        {"prn": prn, "status": {"$in": ["MATCHED", "LOW_CONFIDENCE"]}, "confidence": {"$ne": None}},
        {"confidence": 1}).sort("created_at", DESCENDING).limit(limit)
    return [float(d["confidence"]) for d in cursor]


def mark_logs_committed(draft_id: str, prns: list[str]) -> None:
    try:
        col(C.RECOGNITION_LOGS).update_many({"draft_id": draft_id, "prn": {"$in": prns}},
                                            {"$set": {"committed": True}})
    except PyMongoError as exc:
        logger.warning("could not flag committed logs: %s", exc)


# ---------------------------------------------------------------------- snapshots
def save_snapshot(kind: str, jpeg: bytes, *, session_id: int | None = None, prn: str | None = None,
                  meta: dict[str, Any] | None = None) -> str | None:
    try:
        result = col(C.SNAPSHOTS).insert_one({
            "kind": kind, "image": Binary(jpeg), "content_type": "image/jpeg", "session_id": session_id,
            "prn": prn, "meta": to_builtin(meta or {}), "created_at": utcnow()})
        return str(result.inserted_id)
    except PyMongoError as exc:
        logger.warning("snapshot not stored: %s", exc)
        return None


def get_snapshot(snapshot_id: str) -> dict[str, Any] | None:
    oid = _oid(snapshot_id)
    return col(C.SNAPSHOTS).find_one({"_id": oid}) if oid else None


# ------------------------------------------------------------------------ drafts
# In-memory fallback keeps "analyse -> confirm" working while MongoDB is down.
_fallback_drafts: dict[str, dict[str, Any]] = {}
_fallback_lock = threading.Lock()


def create_draft(doc: dict[str, Any]) -> str:
    settings = get_settings()
    now = utcnow()
    payload = to_builtin(doc)
    payload.update({"status": "OPEN", "created_at": now,
                    "expires_at": now + dt.timedelta(hours=settings.draft_ttl_hours)})
    try:
        return str(col(C.ATTENDANCE_DRAFTS).insert_one(payload).inserted_id)
    except PyMongoError as exc:
        logger.warning("draft stored in memory (MongoDB unavailable): %s", exc)
        draft_id = str(ObjectId())
        with _fallback_lock:
            _fallback_drafts[draft_id] = {**payload, "_id": draft_id}
        return draft_id


def get_draft(draft_id: str) -> dict[str, Any] | None:
    with _fallback_lock:
        if draft_id in _fallback_drafts:
            return dict(_fallback_drafts[draft_id])
    oid = _oid(draft_id)
    return col(C.ATTENDANCE_DRAFTS).find_one({"_id": oid}) if oid else None


def lock_draft(draft_id: str) -> dict[str, Any] | None:
    """Atomic OPEN -> COMMITTING transition: protects against double submission."""
    with _fallback_lock:
        if draft_id in _fallback_drafts:
            draft = _fallback_drafts[draft_id]
            if draft["status"] != "OPEN":
                return None
            draft["status"] = "COMMITTING"
            return dict(draft)
    oid = _oid(draft_id)
    if not oid:
        return None
    return col(C.ATTENDANCE_DRAFTS).find_one_and_update(
        {"_id": oid, "status": "OPEN"}, {"$set": {"status": "COMMITTING", "locked_at": utcnow()}},
        return_document=ReturnDocument.AFTER)


def finish_draft(draft_id: str, result: dict[str, Any]) -> None:
    with _fallback_lock:
        if draft_id in _fallback_drafts:
            _fallback_drafts[draft_id].update({"status": "COMMITTED", "result": result})
            return
    try:
        col(C.ATTENDANCE_DRAFTS).update_one({"_id": _oid(draft_id)}, {"$set": {
            "status": "COMMITTED", "committed_at": utcnow(), "result": to_builtin(result)}})
    except PyMongoError as exc:
        logger.warning("draft %s commit flag not stored: %s", draft_id, exc)


def unlock_draft(draft_id: str) -> None:
    with _fallback_lock:
        if draft_id in _fallback_drafts:
            _fallback_drafts[draft_id]["status"] = "OPEN"
            return
    try:
        col(C.ATTENDANCE_DRAFTS).update_one({"_id": _oid(draft_id), "status": "COMMITTING"},
                                            {"$set": {"status": "OPEN"}})
    except PyMongoError as exc:
        logger.warning("draft %s unlock failed: %s", draft_id, exc)


def upsert_live_seen(draft_id: str | None, session_id: int, created_by: int,
                     seen: dict[str, float]) -> str:
    """LIVE drafts accumulate the best confidence per PRN seen on the webcam stream."""
    if draft_id is None:
        return create_draft({"session_id": session_id, "kind": "LIVE", "created_by": created_by,
                             "candidates": {p: {"confidence": c, "status": "MATCHED"} for p, c in seen.items()}})
    with _fallback_lock:
        if draft_id in _fallback_drafts:
            cands = _fallback_drafts[draft_id].setdefault("candidates", {})
            for prn, conf in seen.items():
                if conf > cands.get(prn, {}).get("confidence", -1):
                    cands[prn] = {"confidence": conf, "status": "MATCHED"}
            return draft_id
    oid = _oid(draft_id)
    for prn, conf in seen.items():
        col(C.ATTENDANCE_DRAFTS).update_one(
            {"_id": oid, "status": "OPEN", "$or": [{f"candidates.{prn}": {"$exists": False}},
                                                   {f"candidates.{prn}.confidence": {"$lt": conf}}]},
            {"$set": {f"candidates.{prn}": {"confidence": float(conf), "status": "MATCHED"}}})
    return draft_id


# --------------------------------------------------------------- aggregations
def daily_recognition_stats(days: int, tz: str) -> list[dict[str, Any]]:
    since = utcnow() - dt.timedelta(days=days)
    pipeline = [
        {"$match": {"created_at": {"$gte": since}}},
        {"$group": {
            "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$created_at", "timezone": tz}},
            "faces": {"$sum": 1},
            "matched": {"$sum": {"$cond": [{"$eq": ["$status", "MATCHED"]}, 1, 0]}},
            "low_confidence": {"$sum": {"$cond": [{"$in": ["$status", ["LOW_CONFIDENCE", "POSSIBLE"]]}, 1, 0]}},
            "unknown": {"$sum": {"$cond": [{"$in": ["$status", ["UNKNOWN", "TOO_SMALL"]]}, 1, 0]}},
            "spoof_suspected": {"$sum": {"$cond": [{"$eq": ["$status", "SPOOF_SUSPECTED"]}, 1, 0]}},
            "avg_confidence": {"$avg": "$confidence"},
            "avg_latency_ms": {"$avg": "$latency_ms"},
        }},
        {"$sort": {"_id": 1}},
        {"$project": {"_id": 0, "day": "$_id", "faces": 1, "matched": 1, "low_confidence": 1, "unknown": 1,
                      "spoof_suspected": 1, "avg_confidence": {"$round": ["$avg_confidence", 3]},
                      "avg_latency_ms": {"$round": ["$avg_latency_ms", 1]}}},
    ]
    return list(col(C.RECOGNITION_LOGS).aggregate(pipeline))


def low_confidence_matches(days: int, limit: int, threshold: float, margin: float) -> list[dict[str, Any]]:
    since = utcnow() - dt.timedelta(days=days)
    pipeline = [
        {"$match": {"created_at": {"$gte": since}, "prn": {"$ne": None},
                    "confidence": {"$gte": threshold - margin, "$lt": threshold + margin}}},
        {"$group": {"_id": "$prn", "occurrences": {"$sum": 1}, "avg_confidence": {"$avg": "$confidence"},
                    "min_confidence": {"$min": "$confidence"}, "last_seen": {"$max": "$created_at"},
                    "sessions": {"$addToSet": "$session_id"}}},
        {"$sort": {"occurrences": -1, "avg_confidence": 1}},
        {"$limit": limit},
        {"$project": {"_id": 0, "prn": "$_id", "occurrences": 1, "avg_confidence": {"$round": ["$avg_confidence", 3]},
                      "min_confidence": {"$round": ["$min_confidence", 3]}, "last_seen": 1,
                      "session_count": {"$size": "$sessions"}}},
    ]
    return list(col(C.RECOGNITION_LOGS).aggregate(pipeline))


def unknown_faces_count(since: dt.datetime, session_ids: list[int] | None = None) -> int:
    query: dict[str, Any] = {"created_at": {"$gte": since}, "status": {"$in": ["UNKNOWN", "TOO_SMALL"]}}
    if session_ids is not None:
        query["session_id"] = {"$in": session_ids}
    return col(C.RECOGNITION_LOGS).count_documents(query)


# --------------------------------------------------------------- privacy
def erase_prn(prn: str) -> dict[str, int]:
    """Right to be forgotten: remove biometric traces of the student."""
    counts = {
        "recognition_logs": col(C.RECOGNITION_LOGS).delete_many({"prn": prn}).deleted_count,
        "snapshots": col(C.SNAPSHOTS).delete_many({"prn": prn}).deleted_count,
    }
    res = col(C.ATTENDANCE_DRAFTS).update_many({f"candidates.{prn}": {"$exists": True}},
                                               {"$unset": {f"candidates.{prn}": ""}})
    counts["drafts_scrubbed"] = res.modified_count
    res = col(C.ATTENDANCE_DRAFTS).update_many({"faces.prn": prn},
                                               {"$set": {"faces.$[f].prn": None, "faces.$[f].name": None}},
                                               array_filters=[{"f.prn": prn}])
    counts["draft_faces_scrubbed"] = res.modified_count
    return counts


def pseudonymise_prn(prn: str, pseudonym: str) -> int:
    """Normal delete keeps statistics but unlinks them from the person."""
    return col(C.RECOGNITION_LOGS).update_many({"prn": prn}, {"$set": {"prn": None, "subject_hash": pseudonym}}
                                               ).modified_count
