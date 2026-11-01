"""Manual overrides (audited by triggers) and the low-confidence review queue."""
from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings
from app.core.crypto import get_cipher
from app.core.deps import CurrentUser
from app.core.errors import AppError, bad_request, conflict, forbidden, not_found
from app.db.mysql import audit_context, transaction
from app.repositories import attendance as att_repo
from app.repositories import embeddings as emb_repo
from app.repositories import notifications as notif_repo
from app.repositories import overrides as ov_repo
from app.repositories import sessions as sessions_repo
from app.schemas.attendance import OverrideCreate, ReviewDecision
from app.services import face_service
from app.services.attendance import assert_can_manage, load_session
from app.services.notify import notify

logger = logging.getLogger(__name__)


def create_override(req: OverrideCreate, actor: CurrentUser) -> dict[str, Any]:
    prn = req.prn.strip().upper()
    with transaction() as conn:
        session = load_session(conn, req.session_id)
        if actor.role == "STUDENT":
            if actor.prn != prn:
                raise forbidden("Students can only request corrections for themselves")
            if session["status"] not in ("OPEN", "CLOSED"):
                raise conflict("This session has not started", "SESSION_NOT_STARTED")
            if ov_repo.has_pending(conn, req.session_id, prn):
                raise conflict("A correction request for this session is already pending", "OVERRIDE_PENDING")
        else:
            assert_can_manage(conn, session, actor)
        if not sessions_repo.is_enrolled(conn, req.session_id, prn):
            raise bad_request("Student is not enrolled in this course", "STUDENT_NOT_ENROLLED")
        record = att_repo.get_record(conn, req.session_id, prn)
        current = record["status"] if record else None
        if current == req.requested_status:
            raise conflict(f"Attendance is already {current}", "NO_CHANGE")
        override_id = ov_repo.create(conn, session_id=req.session_id, prn=prn, current_status=current,
                                     requested_status=req.requested_status, late_minutes=req.late_minutes,
                                     reason=req.reason.strip(), requested_by=actor.user_id)
        applied = actor.is_staff and req.apply_now
        if applied:
            ov_repo.apply(conn, override_id, actor.user_id, "Applied directly by staff")
        out = ov_repo.get(conn, override_id)

    if applied:
        notify("OVERRIDE", "Attendance corrected",
               f"Your attendance for {session['course_code']} on {session['session_date']} was changed to "
               f"{req.requested_status}. Reason: {req.reason}", recipient_prn=prn,
               data={"override_id": override_id})
    else:
        notify("OVERRIDE", "Correction requested",
               f"{prn} requested {req.requested_status} for {session['course_code']} on {session['session_date']}.",
               audience_role="TEACHER", data={"override_id": override_id, "session_id": req.session_id})
    return out or {"override_id": override_id}


def decide_override(override_id: int, approve: bool, note: str | None, actor: CurrentUser) -> dict[str, Any]:
    with transaction() as conn:
        item = ov_repo.get(conn, override_id)
        if not item:
            raise not_found("Override request not found", "OVERRIDE_NOT_FOUND")
        session = load_session(conn, item["session_id"])
        assert_can_manage(conn, session, actor)
        if approve:
            ov_repo.apply(conn, override_id, actor.user_id, note)
        elif not ov_repo.reject(conn, override_id, actor.user_id, note):
            raise conflict("Override request was already resolved", "OVERRIDE_ALREADY_RESOLVED")
        out = ov_repo.get(conn, override_id)
    verdict = "approved" if approve else "rejected"
    notify("OVERRIDE", f"Correction {verdict}",
           f"Your correction request for {item['course_code']} on {item['session_date']} was {verdict}."
           + (f" Note: {note}" if note else ""), recipient_prn=item["prn"], data={"override_id": override_id})
    return out or {}


# ------------------------------------------------------------------ review queue
def decide_review(review_id: str, approve: bool, decision: ReviewDecision, actor: CurrentUser) -> dict[str, Any]:
    item = notif_repo.get_review(review_id)
    if not item:
        raise not_found("Review item not found", "REVIEW_NOT_FOUND")
    if item["status"] != "PENDING":
        raise conflict("Review item already resolved", "REVIEW_RESOLVED")
    session_id = int(item["session_id"])
    result: dict[str, Any] = {}

    if approve:
        prn = (decision.prn or item.get("prn") or "").strip().upper()
        if not prn:
            raise bad_request("Choose the student this face belongs to", "PRN_REQUIRED")
        reason = f"Review queue approval (similarity {float(item['confidence']):.2f})" + (
            f": {decision.note}" if decision.note else "")
        with transaction() as conn:
            session = load_session(conn, session_id)
            assert_can_manage(conn, session, actor)
            if not sessions_repo.is_enrolled(conn, session_id, prn):
                raise bad_request("Student is not enrolled in this course", "STUDENT_NOT_ENROLLED")
            if session["status"] == "OPEN":
                with audit_context(conn, actor.user_id, reason):
                    result["attendance"] = att_repo.mark_present(conn, session_id, prn, "MANUAL", None, actor.user_id)
            else:
                record = att_repo.get_record(conn, session_id, prn)
                if record and record["status"] in ("PRESENT", "LATE"):
                    result["attendance"] = "ALREADY_MARKED"
                else:
                    oid = ov_repo.create(conn, session_id=session_id, prn=prn,
                                         current_status=record["status"] if record else None,
                                         requested_status="PRESENT", late_minutes=None, reason=reason,
                                         requested_by=actor.user_id)
                    ov_repo.apply(conn, oid, actor.user_id, "Approved from review queue")
                    result["attendance"] = "OVERRIDE_APPLIED"
                    result["override_id"] = oid
        if decision.add_to_profile and item.get("embedding_enc"):
            vector = get_cipher().decrypt(item["embedding_enc"])
            engine = face_service.get_engine()
            emb_repo.insert_many([emb_repo.build_doc(prn=prn, vector=vector, model=engine.model_id, source="REVIEW",
                                                     quality={"confidence": float(item["confidence"])})])
            emb_repo.trim_to_limit(prn, get_settings().max_embeddings_per_student)
            face_service.notify_embeddings_changed()
            result["template_added"] = True
        result["prn"] = prn

    resolved = notif_repo.resolve_review(review_id, "APPROVED" if approve else "REJECTED", actor.user_id,
                                         decision.note, result)
    if resolved is None:
        raise AppError(409, "REVIEW_RESOLVED", "Review item was resolved concurrently")
    return {"id": review_id, "status": resolved["status"], **result}
