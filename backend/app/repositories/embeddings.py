"""MongoDB: encrypted face embeddings (many per student)."""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
from bson import Binary, ObjectId
from pymongo import DESCENDING, ReturnDocument

from app.core.crypto import get_cipher
from app.core.utils import to_builtin, utcnow
from app.db.mongo import C, col

logger = logging.getLogger(__name__)


def build_doc(*, prn: str, vector: np.ndarray, model: str, source: str, pose: str | None = None,
              yaw: float | None = None, quality: dict[str, Any] | None = None,
              saga_id: str | None = None) -> dict[str, Any]:
    vec = np.asarray(vector, dtype=np.float32).ravel()
    return {
        "prn": prn,
        "model": model,
        "dim": int(vec.shape[0]),
        "embedding_enc": Binary(get_cipher().encrypt(vec)),
        "pose": pose,
        "yaw": float(yaw) if yaw is not None else None,
        "quality": to_builtin(quality or {}),
        "source": source,
        "active": True,
        "saga_id": saga_id,
        "created_at": utcnow(),
    }


def insert_many(docs: list[dict[str, Any]]) -> list[ObjectId]:
    if not docs:
        return []
    return list(col(C.FACE_EMBEDDINGS).insert_many(docs, ordered=True).inserted_ids)


def load_active(model: str) -> list[tuple[str, np.ndarray]]:
    cipher = get_cipher()
    items: list[tuple[str, np.ndarray]] = []
    cursor = col(C.FACE_EMBEDDINGS).find({"model": model, "active": True}, {"prn": 1, "embedding_enc": 1})
    for doc in cursor:
        try:
            items.append((doc["prn"], cipher.decrypt(doc["embedding_enc"])))
        except ValueError as exc:
            logger.error("Skipping embedding %s: %s", doc.get("_id"), exc)
    return items


def load_for_prn(prn: str, model: str) -> list[np.ndarray]:
    cipher = get_cipher()
    return [cipher.decrypt(d["embedding_enc"])
            for d in col(C.FACE_EMBEDDINGS).find({"prn": prn, "model": model, "active": True})]


def count_for_prn(prn: str, active_only: bool = True) -> int:
    query: dict[str, Any] = {"prn": prn}
    if active_only:
        query["active"] = True
    return col(C.FACE_EMBEDDINGS).count_documents(query)


def counts_by_prn(prns: list[str]) -> dict[str, int]:
    if not prns:
        return {}
    pipeline = [{"$match": {"prn": {"$in": prns}, "active": True}}, {"$group": {"_id": "$prn", "n": {"$sum": 1}}}]
    return {d["_id"]: int(d["n"]) for d in col(C.FACE_EMBEDDINGS).aggregate(pipeline)}


def metadata_for_prn(prn: str) -> list[dict[str, Any]]:
    """Embedding metadata only (never the vectors)."""
    docs = col(C.FACE_EMBEDDINGS).find({"prn": prn}, {"embedding_enc": 0}).sort("created_at", DESCENDING)
    return [{**d, "_id": str(d["_id"])} for d in docs]


def soft_delete_prn(prn: str, saga_id: str) -> int:
    return col(C.FACE_EMBEDDINGS).update_many(
        {"prn": prn, "active": True}, {"$set": {"active": False, "pending_delete": saga_id}}).modified_count


def restore_prn(prn: str, saga_id: str) -> int:
    return col(C.FACE_EMBEDDINGS).update_many(
        {"prn": prn, "pending_delete": saga_id},
        {"$set": {"active": True}, "$unset": {"pending_delete": ""}}).modified_count


def prns_pending_delete(saga_id: str) -> list[str]:
    return list(col(C.FACE_EMBEDDINGS).distinct("prn", {"pending_delete": saga_id}))


def restore_pending_delete(saga_id: str) -> int:
    return col(C.FACE_EMBEDDINGS).update_many(
        {"pending_delete": saga_id}, {"$set": {"active": True}, "$unset": {"pending_delete": ""}}).modified_count


def hard_delete_prn(prn: str) -> int:
    return col(C.FACE_EMBEDDINGS).delete_many({"prn": prn}).deleted_count


def delete_by_saga(saga_id: str) -> int:
    return col(C.FACE_EMBEDDINGS).delete_many({"saga_id": saga_id}).deleted_count


def deactivate_except_saga(prn: str, saga_id: str) -> int:
    """Used when re-enrolling from scratch: retire every older template."""
    return col(C.FACE_EMBEDDINGS).delete_many({"prn": prn, "saga_id": {"$ne": saga_id}}).deleted_count


def trim_to_limit(prn: str, limit: int) -> int:
    """Keep at most `limit` active templates, retiring the oldest AUTO_REENROLL ones first."""
    coll = col(C.FACE_EMBEDDINGS)
    total = coll.count_documents({"prn": prn, "active": True})
    excess = total - limit
    removed = 0
    if excess <= 0:
        return 0
    for source in ("AUTO_REENROLL", "REVIEW", "ADD_PHOTOS", "REGISTRATION"):
        for doc in coll.find({"prn": prn, "active": True, "source": source}, {"_id": 1}).sort("created_at", 1):
            if removed >= excess:
                return removed
            coll.delete_one({"_id": doc["_id"]})
            removed += 1
    return removed


# ----------------------------------------------- index version (cache coherence)
def bump_index_version() -> int:
    doc = col(C.META).find_one_and_update(
        {"_id": "embedding_index"}, {"$inc": {"version": 1}}, upsert=True, return_document=ReturnDocument.AFTER)
    return int(doc["version"])


def get_index_version() -> int:
    doc = col(C.META).find_one({"_id": "embedding_index"})
    return int(doc["version"]) if doc else 0


def total_count() -> int:
    return col(C.FACE_EMBEDDINGS).estimated_document_count()
