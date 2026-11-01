"""Student registration & face enrolment (REGISTER / ADD_PHOTOS sagas).

REGISTER saga
  1. mysql_insert_student   (student row PENDING + user + enrolments)   <- compensate: DELETE student
  2. mongo_insert_embeddings (encrypted templates tagged with saga_id)  <- compensate: delete by saga_id
  3. mysql_mark_enrolled    (face_status = ENROLLED: releases the semantic lock)
  4. refresh_vector_index
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
from sqlalchemy.exc import DBAPIError

from app.config import get_settings
from app.core.deps import CurrentUser
from app.core.errors import AppError, conflict, not_found, translate_db_error, unprocessable
from app.core.security import generate_temp_password, hash_password, validate_password_strength
from app.db.mysql import audit_context, transaction
from app.repositories import embeddings as emb_repo
from app.repositories import students as students_repo
from app.repositories import users as users_repo
from app.repositories.saga import MySQLSagaRecorder
from app.services import face_service
from app.services.notify import notify
from app.services.recognition import (EnrolmentPhoto, analyse_enrolment_photo, enforce_same_person,
                                      find_duplicate, pose_range)
from app.services.saga import Saga, SagaFailed, SagaStep
from app.schemas.students import StudentCreate

logger = logging.getLogger(__name__)


def quality_check(data: bytes, exclude_prn: str | None = None) -> dict[str, Any]:
    """Live feedback for the registration UI (one photo, no writes)."""
    photo = analyse_enrolment_photo(0, data)
    result = photo.public()
    result["duplicate_of"] = None
    if photo.accepted and photo.embedding is not None:
        dup = find_duplicate([photo.embedding], exclude_prn=exclude_prn)
        if dup:
            result["duplicate_of"] = {"prn": dup.prn, "score": round(dup.score, 4)}
    return result


def _process_photos(photos: list[bytes], *, require_pose_variety: bool,
                    exclude_prn: str | None) -> list[EnrolmentPhoto]:
    s = get_settings()
    if len(photos) < s.min_reg_photos or len(photos) > s.max_reg_photos:
        raise unprocessable(f"Upload between {s.min_reg_photos} and {s.max_reg_photos} photos "
                            f"(received {len(photos)})", "PHOTO_COUNT")
    analysed = [analyse_enrolment_photo(i, data) for i, data in enumerate(photos)]
    enforce_same_person(analysed)
    accepted = [p for p in analysed if p.accepted]
    report = [p.public() for p in analysed]
    if len(accepted) < s.min_reg_photos:
        raise unprocessable(
            f"Only {len(accepted)} of {len(photos)} photos passed the quality checks; "
            f"at least {s.min_reg_photos} are required", "PHOTO_QUALITY", {"photos": report})
    spread = pose_range(analysed)
    engine = face_service.get_engine()
    if require_pose_variety and engine.supports_pose and spread is not None and spread < s.reg_min_yaw_range:
        raise unprocessable(
            f"Photos look identical (head turn {spread:.0f} deg). Capture front, left and right views",
            "POSE_VARIETY", {"photos": report, "yaw_range": spread})
    dup = find_duplicate([p.embedding for p in accepted], exclude_prn=exclude_prn)
    if dup:
        notify("SPOOF", "Duplicate face blocked",
               f"A registration attempt matched existing student {dup.prn} (similarity {dup.score:.2f}).",
               audience_role="ADMIN", data={"existing_prn": dup.prn, "score": dup.score})
        raise conflict(f"This face is already registered under PRN {dup.prn}", "DUPLICATE_FACE",
                       {"existing_prn": dup.prn, "score": round(dup.score, 4), "photos": report})
    return analysed


def _embedding_docs(prn: str, photos: list[EnrolmentPhoto], source: str, saga_id: str) -> list[dict[str, Any]]:
    model = face_service.get_engine().model_id
    return [emb_repo.build_doc(prn=prn, vector=p.embedding, model=model, source=source, pose=p.pose, yaw=p.yaw,
                               quality=p.quality.get("metrics"), saga_id=saga_id)
            for p in photos if p.accepted and p.embedding is not None]


def register_student(payload: StudentCreate, photos: list[bytes], actor: CurrentUser) -> dict[str, Any]:
    if payload.password:
        validate_password_strength(payload.password)

    # ---------------- pre-checks (no writes) ----------------
    with transaction() as conn:
        if students_repo.exists(conn, payload.prn):
            raise conflict(f"PRN {payload.prn} is already registered", "PRN_EXISTS")
        if students_repo.email_taken(conn, payload.email):
            raise conflict("E-mail is already used by another student", "EMAIL_EXISTS")
        division = students_repo.find_division(conn, payload.branch, payload.year, payload.division)
        if not division:
            raise unprocessable(f"Unknown division {payload.branch}-{payload.year}-{payload.division}",
                                "UNKNOWN_DIVISION")
        if students_repo.roll_taken(conn, division["division_id"], payload.roll_no):
            raise conflict(f"Roll number {payload.roll_no} is already taken in this division", "ROLL_EXISTS")

    analysed = _process_photos(photos, require_pose_variety=True, exclude_prn=None)
    temp_password = payload.password or generate_temp_password()
    password_hash = hash_password(temp_password)

    # ---------------- saga steps ----------------
    def mysql_insert(ctx: dict[str, Any]) -> None:
        with transaction() as conn:
            with audit_context(conn, actor.user_id, "registration"):
                students_repo.insert_student(conn, {
                    "prn": payload.prn, "full_name": payload.full_name, "email": payload.email,
                    "phone": payload.phone, "division_id": division["division_id"], "roll_no": payload.roll_no,
                    "face_status": "PENDING"})
                ctx["user_id"] = users_repo.create_user(conn, username=payload.prn, password_hash=password_hash,
                                                        role="STUDENT", prn=payload.prn,
                                                        must_change=payload.password is None)
                ctx["courses_enrolled"] = students_repo.auto_enroll(conn, payload.prn, division["branch_id"],
                                                                    payload.year)

    def mysql_delete(_: dict[str, Any]) -> None:
        with transaction() as conn:
            with audit_context(conn, actor.user_id, "registration rolled back (saga compensation)"):
                students_repo.delete_student(conn, payload.prn)

    def mongo_insert(ctx: dict[str, Any]) -> None:
        docs = _embedding_docs(payload.prn, analysed, "REGISTRATION", ctx["saga_id"])
        ctx["embedding_ids"] = [str(i) for i in emb_repo.insert_many(docs)]

    def mongo_delete(ctx: dict[str, Any]) -> None:
        emb_repo.delete_by_saga(ctx["saga_id"])

    def mysql_enrolled(_: dict[str, Any]) -> None:
        with transaction() as conn:
            students_repo.set_face_status(conn, payload.prn, "ENROLLED")

    def index_refresh(_: dict[str, Any]) -> None:
        face_service.notify_embeddings_changed()

    saga = Saga("REGISTER", payload.prn, [
        SagaStep("mysql_insert_student", mysql_insert, mysql_delete),
        SagaStep("mongo_insert_embeddings", mongo_insert, mongo_delete),
        SagaStep("mysql_mark_enrolled", mysql_enrolled, None),
        SagaStep("refresh_vector_index", index_refresh, None),
    ], MySQLSagaRecorder(), created_by=actor.user_id)
    try:
        ctx = saga.run()
    except SagaFailed as exc:
        if isinstance(exc.cause, AppError):
            raise exc.cause from exc
        mapped = translate_db_error(exc.cause) if isinstance(exc.cause, DBAPIError) else None
        if mapped is not None and mapped.status_code < 500:
            raise mapped from exc  # e.g. concurrent duplicate PRN -> 409
        raise AppError(503, "REGISTRATION_ROLLED_BACK" if exc.compensated else "REGISTRATION_FAILED",
                       "Registration could not be completed and was rolled back. Please retry."
                       if exc.compensated else "Registration failed; recovery job will clean up",
                       {"saga_id": exc.saga_id, "failed_step": exc.step}) from exc

    notify("SYSTEM", "Student registered", f"{payload.full_name} ({payload.prn}) enrolled with "
           f"{len(ctx.get('embedding_ids', []))} face templates.", audience_role="ADMIN",
           data={"prn": payload.prn})
    logger.info("Registered %s with %d templates (saga %s)", payload.prn, len(ctx["embedding_ids"]), ctx["saga_id"])
    with transaction() as conn:
        student = students_repo.get_student(conn, payload.prn)
    return {
        "student": student,
        "saga_id": ctx["saga_id"],
        "embeddings_stored": len(ctx["embedding_ids"]),
        "courses_enrolled": ctx.get("courses_enrolled", 0),
        "photos": [p.public() for p in analysed],
        "temp_password": None if payload.password else temp_password,
        "username": payload.prn,
    }


def add_photos(prn: str, photos: list[bytes], replace: bool, actor: CurrentUser) -> dict[str, Any]:
    """Re-enrolment (ADD_PHOTOS saga). With replace=True all old templates are retired."""
    s = get_settings()
    with transaction() as conn:
        student = students_repo.get_student(conn, prn)
    if not student:
        raise not_found("Student not found", "STUDENT_NOT_FOUND")
    analysed = _process_photos(photos, require_pose_variety=replace, exclude_prn=prn)
    engine = face_service.get_engine()

    if not replace:
        existing = emb_repo.load_for_prn(prn, engine.model_id)
        if existing:
            centroid = np.mean(np.stack(existing), axis=0)
            centroid /= np.linalg.norm(centroid) or 1.0
            sims = [float(np.dot(p.embedding, centroid)) for p in analysed if p.accepted]
            if sims and max(sims) < face_service.match_threshold():
                raise conflict("New photos do not match the enrolled face. Use replace=true to re-enrol "
                               "from scratch (admin).", "FACE_MISMATCH", {"best_similarity": round(max(sims), 4)})

    def mongo_insert(ctx: dict[str, Any]) -> None:
        source = "REGISTRATION" if replace else "ADD_PHOTOS"
        ctx["embedding_ids"] = [str(i) for i in emb_repo.insert_many(_embedding_docs(prn, analysed, source,
                                                                                    ctx["saga_id"]))]

    def mongo_delete(ctx: dict[str, Any]) -> None:
        emb_repo.delete_by_saga(ctx["saga_id"])

    def retire_old(ctx: dict[str, Any]) -> None:
        ctx["retired"] = emb_repo.deactivate_except_saga(prn, ctx["saga_id"]) if replace else \
            emb_repo.trim_to_limit(prn, s.max_embeddings_per_student)

    def mysql_enrolled(_: dict[str, Any]) -> None:
        with transaction() as conn:
            students_repo.set_face_status(conn, prn, "ENROLLED")

    saga = Saga("ADD_PHOTOS", prn, [
        SagaStep("mongo_insert_embeddings", mongo_insert, mongo_delete),
        SagaStep("mongo_retire_old_templates", retire_old, None, pivot=True),
        SagaStep("mysql_mark_enrolled", mysql_enrolled, None),
        SagaStep("refresh_vector_index", lambda _ctx: face_service.notify_embeddings_changed(), None),
    ], MySQLSagaRecorder(), created_by=actor.user_id)
    try:
        ctx = saga.run()
    except SagaFailed as exc:
        raise AppError(503, "ENROLMENT_FAILED", "Could not store the new face templates, please retry",
                       {"saga_id": exc.saga_id, "failed_step": exc.step}) from exc
    notify("REENROLL", "Face profile updated", "Your face profile was updated by staff.", recipient_prn=prn)
    return {"prn": prn, "saga_id": ctx["saga_id"], "embeddings_added": len(ctx["embedding_ids"]),
            "templates_retired": ctx.get("retired", 0), "photos": [p.public() for p in analysed],
            "total_templates": emb_repo.count_for_prn(prn)}
