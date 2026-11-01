"""MongoDB: notifications, spoof attempts, low-confidence review queue."""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from bson import Binary, ObjectId
from bson.errors import InvalidId
from pymongo import DESCENDING, ReturnDocument
from pymongo.errors import PyMongoError

from app.core.utils import to_builtin, utcnow
from app.db.mongo import C, col

logger = logging.getLogger(__name__)


def _oid(value: str) -> ObjectId | None:
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return None


def _public(doc: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in doc.items() if k not in ("embedding_enc", "image")}
    out["id"] = str(out.pop("_id"))
    return out


# ------------------------------------------------------------------ notifications
def create_notification(*, type_: str, title: str, message: str, recipient_prn: str | None = None,
                        recipient_user_id: int | None = None, audience_role: str | None = None,
                        data: dict[str, Any] | None = None, channel: str = "in_app") -> dict[str, Any] | None:
    doc = {
        "type": type_, "title": title, "message": message, "recipient_prn": recipient_prn,
        "recipient_user_id": recipient_user_id, "audience_role": audience_role,
        "data": to_builtin(data or {}), "channel": channel, "read_by": [], "created_at": utcnow(),
    }
    try:
        doc["_id"] = col(C.NOTIFICATIONS).insert_one(doc).inserted_id
        return _public(doc)
    except PyMongoError as exc:
        logger.warning("notification not stored: %s", exc)
        return None


def _visibility(user_id: int, role: str, prn: str | None) -> dict[str, Any]:
    clauses: list[dict[str, Any]] = [{"recipient_user_id": user_id}, {"audience_role": role}]
    if prn:
        clauses.append({"recipient_prn": prn})
    if role == "ADMIN":
        clauses.append({"audience_role": "TEACHER"})
    return {"$or": clauses}


def list_for_user(user_id: int, role: str, prn: str | None, limit: int = 50) -> list[dict[str, Any]]:
    docs = col(C.NOTIFICATIONS).find(_visibility(user_id, role, prn)).sort("created_at", DESCENDING).limit(limit)
    out = []
    for d in docs:
        item = _public(d)
        item["read"] = user_id in (d.get("read_by") or [])
        item.pop("read_by", None)
        out.append(item)
    return out


def unread_count(user_id: int, role: str, prn: str | None) -> int:
    query = _visibility(user_id, role, prn)
    query["read_by"] = {"$ne": user_id}
    return col(C.NOTIFICATIONS).count_documents(query)


def mark_read(notification_id: str | None, user_id: int, role: str, prn: str | None) -> int:
    query = _visibility(user_id, role, prn)
    if notification_id:
        oid = _oid(notification_id)
        if not oid:
            return 0
        query = {"$and": [query, {"_id": oid}]}
    return col(C.NOTIFICATIONS).update_many(query, {"$addToSet": {"read_by": user_id}}).modified_count


def recently_notified(type_: str, prn: str, days: int) -> bool:
    since = utcnow() - dt.timedelta(days=days)
    return col(C.NOTIFICATIONS).count_documents(
        {"type": type_, "recipient_prn": prn, "created_at": {"$gte": since}}, limit=1) > 0


def delete_for_prn(prn: str) -> int:
    return col(C.NOTIFICATIONS).delete_many({"recipient_prn": prn}).deleted_count


# ------------------------------------------------------------------ spoof attempts
def log_spoof(*, endpoint: str, reasons: list[str], prn: str | None, session_id: int | None,
              metrics: dict[str, Any], snapshot_id: str | None, actor_id: int | None,
              client_ip: str | None) -> str | None:
    try:
        return str(col(C.SPOOF_ATTEMPTS).insert_one({
            "endpoint": endpoint, "reasons": reasons, "prn": prn, "session_id": session_id,
            "metrics": to_builtin(metrics), "snapshot_id": snapshot_id, "actor_id": actor_id,
            "client_ip": client_ip, "created_at": utcnow()}).inserted_id)
    except PyMongoError as exc:
        logger.warning("spoof attempt not logged: %s", exc)
        return None


def spoof_per_day(days: int, tz: str) -> list[dict[str, Any]]:
    since = utcnow() - dt.timedelta(days=days)
    pipeline = [
        {"$match": {"created_at": {"$gte": since}}},
        {"$project": {"day": {"$dateToString": {"format": "%Y-%m-%d", "date": "$created_at", "timezone": tz}},
                      "reasons": 1}},
        {"$facet": {
            "totals": [{"$group": {"_id": "$day", "attempts": {"$sum": 1}}}],
            "reasons": [{"$unwind": "$reasons"},
                        {"$group": {"_id": {"day": "$day", "reason": "$reasons"}, "n": {"$sum": 1}}}],
        }},
    ]
    result = next(col(C.SPOOF_ATTEMPTS).aggregate(pipeline), {"totals": [], "reasons": []})
    days_out: dict[str, dict[str, Any]] = {
        t["_id"]: {"day": t["_id"], "attempts": int(t["attempts"]), "by_reason": {}} for t in result["totals"]}
    for r in result["reasons"]:
        day = r["_id"]["day"]
        days_out.setdefault(day, {"day": day, "attempts": 0, "by_reason": {}})["by_reason"][r["_id"]["reason"]] = r["n"]
    return [days_out[d] for d in sorted(days_out)]


def recent_spoofs(limit: int = 20) -> list[dict[str, Any]]:
    return [_public(d) for d in col(C.SPOOF_ATTEMPTS).find().sort("created_at", DESCENDING).limit(limit)]


def spoof_count_since(since: dt.datetime) -> int:
    return col(C.SPOOF_ATTEMPTS).count_documents({"created_at": {"$gte": since}})


def delete_spoofs_for_prn(prn: str) -> int:
    return col(C.SPOOF_ATTEMPTS).delete_many({"prn": prn}).deleted_count


# ------------------------------------------------------------------ review queue
def create_review(*, session_id: int, prn: str | None, confidence: float, status_hint: str,
                  embedding_enc: bytes | None, snapshot_id: str | None, source: str,
                  suggestions: list[dict[str, Any]], created_by: int | None) -> str | None:
    try:
        return str(col(C.REVIEW_QUEUE).insert_one({
            "session_id": int(session_id), "prn": prn, "confidence": float(confidence), "match_status": status_hint,
            "embedding_enc": Binary(embedding_enc) if embedding_enc else None, "snapshot_id": snapshot_id,
            "source": source, "suggestions": to_builtin(suggestions), "status": "PENDING",
            "created_by": created_by, "created_at": utcnow()}).inserted_id)
    except PyMongoError as exc:
        logger.warning("review item not stored: %s", exc)
        return None


def list_reviews(status: str | None, limit: int = 100) -> list[dict[str, Any]]:
    query = {"status": status} if status else {}
    return [_public(d) for d in col(C.REVIEW_QUEUE).find(query).sort("created_at", DESCENDING).limit(limit)]


def get_review(review_id: str) -> dict[str, Any] | None:
    oid = _oid(review_id)
    return col(C.REVIEW_QUEUE).find_one({"_id": oid}) if oid else None


def resolve_review(review_id: str, status: str, user_id: int, note: str | None,
                   result: dict[str, Any] | None = None) -> dict[str, Any] | None:
    oid = _oid(review_id)
    if not oid:
        return None
    return col(C.REVIEW_QUEUE).find_one_and_update(
        {"_id": oid, "status": "PENDING"},
        {"$set": {"status": status, "resolved_by": user_id, "resolved_at": utcnow(), "note": note,
                  "result": to_builtin(result or {})}},
        return_document=ReturnDocument.AFTER)


def pending_review_count() -> int:
    return col(C.REVIEW_QUEUE).count_documents({"status": "PENDING"})


def delete_reviews_for_prn(prn: str) -> int:
    return col(C.REVIEW_QUEUE).delete_many({"prn": prn}).deleted_count
