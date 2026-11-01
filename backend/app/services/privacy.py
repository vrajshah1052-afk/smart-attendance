"""Delete student / right-to-be-forgotten (DELETE + FORGET sagas) and saga recovery.

DELETE / FORGET saga
  1. mongo_soft_delete   embeddings active=false  (stops recognition at once)  <- compensate: restore
  2. mysql_delete        PIVOT: rows + cascades (FORGET uses forget_student()) -- no way back after this
  3. mongo_purge         hard delete templates (+ logs/snapshots/notifications for FORGET), idempotent
  4. refresh index
Steps after the pivot are retried by the recovery job if they fail.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any

from app.core.deps import CurrentUser
from app.core.errors import AppError, not_found
from app.db.mysql import audit_context, call_procedure, transaction
from app.repositories import embeddings as emb_repo
from app.repositories import logs as logs_repo
from app.repositories import notifications as notif_repo
from app.repositories import saga as saga_repo
from app.repositories import students as students_repo
from app.repositories.saga import MySQLSagaRecorder
from app.services import face_service
from app.services.saga import Saga, SagaFailed, SagaStep

logger = logging.getLogger(__name__)


def subject_hash(prn: str) -> str:
    return hashlib.sha256(prn.encode("utf-8")).hexdigest()


def _purge_mongo(prn: str, forget: bool) -> dict[str, int]:
    counts = {"face_embeddings": emb_repo.hard_delete_prn(prn)}
    if forget:
        counts.update(logs_repo.erase_prn(prn))
        counts["notifications"] = notif_repo.delete_for_prn(prn)
        counts["spoof_attempts"] = notif_repo.delete_spoofs_for_prn(prn)
        counts["review_queue"] = notif_repo.delete_reviews_for_prn(prn)
    else:
        counts["recognition_logs_pseudonymised"] = logs_repo.pseudonymise_prn(prn, subject_hash(prn))
    return counts


def remove_student(prn: str, actor: CurrentUser, forget: bool, reason: str | None = None) -> dict[str, Any]:
    with transaction() as conn:
        student = students_repo.get_student(conn, prn)
    if not student:
        raise not_found("Student not found", "STUDENT_NOT_FOUND")

    saga_type = "FORGET" if forget else "DELETE"
    subject = subject_hash(prn) if forget else prn

    def soft_delete(ctx: dict[str, Any]) -> None:
        ctx["soft_deleted"] = emb_repo.soft_delete_prn(prn, ctx["saga_id"])
        face_service.notify_embeddings_changed()

    def restore(ctx: dict[str, Any]) -> None:
        emb_repo.restore_prn(prn, ctx["saga_id"])
        face_service.notify_embeddings_changed()

    def mysql_delete(ctx: dict[str, Any]) -> None:
        with transaction() as conn:
            if forget:
                (deleted,) = call_procedure(conn, "forget_student", [prn, actor.user_id], out_count=1)
            else:
                with audit_context(conn, actor.user_id, reason or "student deleted"):
                    deleted = students_repo.delete_student(conn, prn)
        ctx["mysql_deleted"] = int(deleted or 0)

    def purge(ctx: dict[str, Any]) -> None:
        ctx["mongo"] = _purge_mongo(prn, forget)

    saga = Saga(saga_type, subject, [
        SagaStep("mongo_soft_delete_embeddings", soft_delete, restore),
        SagaStep("mysql_delete_student", mysql_delete, None, pivot=True),
        SagaStep("mongo_purge", purge, None),
        SagaStep("refresh_vector_index", lambda _c: face_service.notify_embeddings_changed(), None),
    ], MySQLSagaRecorder(), created_by=actor.user_id)
    try:
        ctx = saga.run()
    except SagaFailed as exc:
        if exc.compensated or exc.step == "mongo_soft_delete_embeddings":
            raise AppError(503, "DELETE_ROLLED_BACK", "Deletion failed and was rolled back; nothing was removed",
                           {"saga_id": exc.saga_id}) from exc
        raise AppError(202, "DELETE_PENDING", "Student removed from MySQL; remaining MongoDB clean-up will be "
                       "retried automatically", {"saga_id": exc.saga_id}) from exc
    logger.info("%s saga %s finished for %s", saga_type, ctx["saga_id"], subject[:12])
    return {
        "saga_id": ctx["saga_id"],
        "mode": saga_type,
        "subject": subject if forget else prn,
        "mysql": {"students_deleted": ctx.get("mysql_deleted", 0),
                  "cascaded": ["users", "enrollments", "attendance", "override_requests"]},
        "mongo": ctx.get("mongo", {}),
        "certificate": f"{saga_type}-{ctx['saga_id']}",
    }


def recover_sagas(older_than_minutes: int = 5) -> dict[str, int]:
    """Crash recovery: finish or compensate sagas left half-way."""
    fixed = {"completed": 0, "compensated": 0, "skipped": 0}
    recorder = MySQLSagaRecorder()
    for saga in saga_repo.stale_sagas(older_than_minutes):
        sid, stype, subject = saga["saga_id"], saga["saga_type"], saga["subject"]
        try:
            if stype == "REGISTER":
                with transaction() as conn:
                    student = students_repo.get_student(conn, subject)
                templates = emb_repo.count_for_prn(subject, active_only=False)
                if student and templates and student["face_status"] == "PENDING":
                    with transaction() as conn:
                        students_repo.set_face_status(conn, subject, "ENROLLED")
                    recorder.status(sid, "COMPLETED", "recovered: forward")
                    fixed["completed"] += 1
                else:
                    emb_repo.delete_by_saga(sid)
                    if student and student["face_status"] == "PENDING":
                        with transaction() as conn:
                            students_repo.delete_student(conn, subject)
                    recorder.status(sid, "COMPENSATED", "recovered: backward")
                    fixed["compensated"] += 1
            elif stype in ("DELETE", "FORGET"):
                steps = {s["name"]: s["status"] for s in saga.get("steps", [])}
                if steps.get("mysql_delete_student") == "DONE":
                    # past the pivot: forward recovery. FORGET subjects are hashed, but the
                    # soft-deleted templates still carry the PRN, so the purge can be re-run.
                    prns = emb_repo.prns_pending_delete(sid) or ([subject] if stype == "DELETE" else [])
                    for prn in prns:
                        _purge_mongo(prn, forget=stype == "FORGET")
                    recorder.status(sid, "COMPLETED", "recovered: forward purge")
                    fixed["completed"] += 1
                else:
                    restored = emb_repo.restore_pending_delete(sid)
                    recorder.status(sid, "COMPENSATED", f"recovered: restored {restored} templates")
                    fixed["compensated"] += 1
            else:
                emb_repo.delete_by_saga(sid)
                recorder.status(sid, "COMPENSATED", "recovered")
                fixed["compensated"] += 1
        except Exception as exc:  # noqa: BLE001
            logger.error("Saga recovery for %s failed: %s", sid, exc)
            fixed["skipped"] += 1
    if any(fixed.values()):
        face_service.notify_embeddings_changed()
        logger.info("Saga recovery: %s", fixed)
    return fixed
