"""Idempotent MongoDB schema: $jsonSchema validators + compound/TTL indexes.

Mirrors db/mongo/init-mongo.js so a brand-new database (e.g. the pytest DB)
is configured by the application itself. TTL values follow the settings and
are reconciled with collMod when they change.
"""
from __future__ import annotations

import logging
from typing import Any

from pymongo import ASCENDING, DESCENDING
from pymongo.database import Database
from pymongo.errors import CollectionInvalid, OperationFailure

from app.config import Settings
from app.db.mongo import C

logger = logging.getLogger(__name__)

DAY = 86400
NUM = ["double", "int", "long", "decimal"]

VALIDATORS: dict[str, dict[str, Any]] = {
    C.FACE_EMBEDDINGS: {"$jsonSchema": {
        "bsonType": "object",
        "required": ["prn", "model", "dim", "embedding_enc", "source", "active", "created_at"],
        "properties": {
            "prn": {"bsonType": "string", "pattern": "^[A-Z0-9]{6,20}$"},
            "model": {"bsonType": "string"},
            "dim": {"bsonType": ["int", "long"], "minimum": 64, "maximum": 4096},
            "embedding_enc": {"bsonType": "binData"},
            "pose": {"bsonType": ["string", "null"]},
            "yaw": {"bsonType": NUM + ["null"]},
            "quality": {"bsonType": "object"},
            "source": {"enum": ["REGISTRATION", "ADD_PHOTOS", "AUTO_REENROLL", "REVIEW", "SYNTHETIC"]},
            "active": {"bsonType": "bool"},
            "saga_id": {"bsonType": ["string", "null"]},
            "created_at": {"bsonType": "date"},
        },
    }},
    C.RECOGNITION_LOGS: {"$jsonSchema": {
        "bsonType": "object",
        "required": ["kind", "status", "created_at"],
        "properties": {
            "kind": {"enum": ["GROUP", "SOLO", "LIVE", "QR"]},
            "status": {"enum": ["MATCHED", "LOW_CONFIDENCE", "POSSIBLE", "UNKNOWN", "SPOOF_SUSPECTED", "TOO_SMALL"]},
            "prn": {"bsonType": ["string", "null"]},
            "confidence": {"bsonType": NUM + ["null"]},
            "session_id": {"bsonType": ["int", "long", "null"]},
            "created_at": {"bsonType": "date"},
        },
    }},
    C.SNAPSHOTS: {"$jsonSchema": {
        "bsonType": "object",
        "required": ["kind", "image", "created_at"],
        "properties": {
            "kind": {"enum": ["GROUP_ANNOTATED", "UNKNOWN_FACE", "SPOOF", "LATE", "REVIEW_FACE"]},
            "image": {"bsonType": "binData"},
            "content_type": {"bsonType": "string"},
            "created_at": {"bsonType": "date"},
        },
    }},
    C.NOTIFICATIONS: {"$jsonSchema": {
        "bsonType": "object",
        "required": ["type", "title", "message", "created_at"],
        "properties": {
            "type": {"enum": ["LATE", "SHORTAGE", "UNKNOWN_FACE", "SPOOF", "REENROLL", "OVERRIDE", "SESSION",
                              "SYSTEM", "DAILY_SUMMARY", "REVIEW", "ATTENDANCE"]},
            "title": {"bsonType": "string"},
            "message": {"bsonType": "string"},
            "recipient_prn": {"bsonType": ["string", "null"]},
            "recipient_user_id": {"bsonType": ["int", "long", "null"]},
            "audience_role": {"enum": ["ADMIN", "TEACHER", "STUDENT", None]},
            "read_by": {"bsonType": "array"},
            "created_at": {"bsonType": "date"},
        },
    }},
    C.SPOOF_ATTEMPTS: {"$jsonSchema": {
        "bsonType": "object",
        "required": ["endpoint", "reasons", "created_at"],
        "properties": {
            "endpoint": {"bsonType": "string"},
            "reasons": {"bsonType": "array", "items": {"bsonType": "string"}},
            "prn": {"bsonType": ["string", "null"]},
            "session_id": {"bsonType": ["int", "long", "null"]},
            "created_at": {"bsonType": "date"},
        },
    }},
    C.REVIEW_QUEUE: {"$jsonSchema": {
        "bsonType": "object",
        "required": ["session_id", "status", "confidence", "created_at"],
        "properties": {
            "session_id": {"bsonType": ["int", "long"]},
            "prn": {"bsonType": ["string", "null"]},
            "confidence": {"bsonType": NUM},
            "status": {"enum": ["PENDING", "APPROVED", "REJECTED"]},
            "created_at": {"bsonType": "date"},
        },
    }},
    C.ATTENDANCE_DRAFTS: {"$jsonSchema": {
        "bsonType": "object",
        "required": ["session_id", "kind", "status", "created_at", "expires_at"],
        "properties": {
            "session_id": {"bsonType": ["int", "long"]},
            "kind": {"enum": ["GROUP", "LIVE"]},
            "status": {"enum": ["OPEN", "COMMITTING", "COMMITTED"]},
            "created_at": {"bsonType": "date"},
            "expires_at": {"bsonType": "date"},
        },
    }},
}


def _indexes(settings: Settings) -> dict[str, list[tuple[list[tuple[str, int]], dict[str, Any]]]]:
    return {
        C.FACE_EMBEDDINGS: [
            ([("prn", ASCENDING), ("created_at", DESCENDING)], {"name": "prn_created"}),
            ([("model", ASCENDING), ("active", ASCENDING)], {"name": "model_active"}),
            ([("saga_id", ASCENDING)], {"name": "saga", "sparse": True}),
        ],
        C.RECOGNITION_LOGS: [
            ([("prn", ASCENDING), ("created_at", DESCENDING)], {"name": "prn_created"}),
            ([("session_id", ASCENDING)], {"name": "session"}),
            ([("status", ASCENDING), ("created_at", DESCENDING)], {"name": "status_created"}),
            ([("created_at", ASCENDING)], {"name": "ttl_created_at",
                                           "expireAfterSeconds": settings.recognition_log_ttl_days * DAY}),
        ],
        C.SNAPSHOTS: [
            ([("created_at", ASCENDING)], {"name": "ttl_created_at",
                                           "expireAfterSeconds": settings.snapshot_ttl_days * DAY}),
            ([("session_id", ASCENDING)], {"name": "session"}),
            ([("prn", ASCENDING)], {"name": "prn", "sparse": True}),
        ],
        C.NOTIFICATIONS: [
            ([("recipient_prn", ASCENDING), ("created_at", DESCENDING)], {"name": "prn_created"}),
            ([("recipient_user_id", ASCENDING), ("created_at", DESCENDING)], {"name": "user_created"}),
            ([("audience_role", ASCENDING), ("created_at", DESCENDING)], {"name": "role_created"}),
            ([("created_at", ASCENDING)], {"name": "ttl_created_at", "expireAfterSeconds": 180 * DAY}),
        ],
        C.SPOOF_ATTEMPTS: [
            ([("created_at", DESCENDING)], {"name": "created"}),
            ([("prn", ASCENDING), ("created_at", DESCENDING)], {"name": "prn_created"}),
        ],
        C.REVIEW_QUEUE: [
            ([("status", ASCENDING), ("created_at", DESCENDING)], {"name": "status_created"}),
            ([("prn", ASCENDING)], {"name": "prn"}),
        ],
        C.ATTENDANCE_DRAFTS: [
            ([("expires_at", ASCENDING)], {"name": "ttl_expires_at", "expireAfterSeconds": 0}),
            ([("session_id", ASCENDING), ("status", ASCENDING)], {"name": "session_status"}),
        ],
        C.LIVENESS_NONCES: [
            ([("nonce", ASCENDING)], {"name": "nonce_unique", "unique": True}),
            ([("created_at", ASCENDING)], {"name": "ttl_created_at", "expireAfterSeconds": 600}),
        ],
    }


def ensure_mongo_schema(db: Database, settings: Settings) -> None:
    existing = set(db.list_collection_names())
    for name, validator in VALIDATORS.items():
        if name not in existing:
            try:
                db.create_collection(name, validator=validator, validationLevel="strict")
            except CollectionInvalid:
                pass
        else:
            try:
                db.command({"collMod": name, "validator": validator, "validationLevel": "strict"})
            except OperationFailure as exc:
                logger.warning("collMod validator on %s failed: %s", name, exc)
    for name in (C.LIVENESS_NONCES, C.META):
        if name not in existing:
            try:
                db.create_collection(name)
            except CollectionInvalid:
                pass

    for coll_name, specs in _indexes(settings).items():
        coll = db[coll_name]
        for keys, options in specs:
            try:
                coll.create_index(keys, **options)
            except OperationFailure as exc:
                # 85/86: same name, different options (e.g. TTL changed) -> reconcile
                if exc.code in (85, 86) and "expireAfterSeconds" in options:
                    db.command({"collMod": coll_name, "index": {
                        "name": options["name"], "expireAfterSeconds": options["expireAfterSeconds"]}})
                    logger.info("Updated TTL of %s.%s", coll_name, options["name"])
                else:
                    logger.warning("Index %s on %s not created: %s", options.get("name"), coll_name, exc)

    db[C.META].update_one({"_id": "embedding_index"}, {"$setOnInsert": {"version": 0}}, upsert=True)
    logger.info("MongoDB schema ensured on database '%s'", db.name)
