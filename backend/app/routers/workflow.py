"""Manual overrides, low-confidence review queue, notifications."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from app.core.deps import CurrentUser, get_current_user, require_staff
from app.core.errors import not_found
from app.db.mysql import transaction
from app.repositories import logs as logs_repo
from app.repositories import notifications as notif_repo
from app.repositories import overrides as ov_repo
from app.repositories import students as students_repo
from app.schemas.attendance import Decision, OverrideCreate, ReviewDecision
from app.services import overrides as ov_service

router = APIRouter(tags=["workflow"])


# ------------------------------------------------------------------ overrides
@router.post("/overrides", status_code=201, summary="Request (student) or apply (staff) a manual override")
def create_override(body: OverrideCreate, user: CurrentUser = Depends(get_current_user)) -> dict:
    return ov_service.create_override(body, user)


@router.get("/overrides", summary="List override requests")
def list_overrides(status: str | None = Query(None, pattern="^(PENDING|APPROVED|REJECTED)$"),
                   prn: str | None = None, mine: bool = False,
                   user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    with transaction() as conn:
        if user.role == "STUDENT":
            return ov_repo.list_overrides(conn, status=status, prn=user.prn, teacher_id=None)
        return ov_repo.list_overrides(conn, status=status, prn=prn.upper() if prn else None,
                                      teacher_id=user.teacher_id if mine and user.teacher_id else None)


@router.post("/overrides/{override_id}/approve", summary="Approve: procedure apply_override (audited)")
def approve_override(override_id: int, body: Decision, user: CurrentUser = Depends(require_staff)) -> dict:
    return ov_service.decide_override(override_id, True, body.note, user)


@router.post("/overrides/{override_id}/reject", summary="Reject an override request")
def reject_override(override_id: int, body: Decision, user: CurrentUser = Depends(require_staff)) -> dict:
    return ov_service.decide_override(override_id, False, body.note, user)


# ------------------------------------------------------------------ review queue
@router.get("/review", summary="Low-confidence review queue")
def list_review(status: str | None = Query("PENDING", pattern="^(PENDING|APPROVED|REJECTED)$"),
                _: CurrentUser = Depends(require_staff)) -> list[dict]:
    items = notif_repo.list_reviews(status)
    prns = [i["prn"] for i in items if i.get("prn")] + [s["prn"] for i in items for s in i.get("suggestions") or []]
    with transaction() as conn:
        names = students_repo.names_for(conn, list(set(prns)))
    for item in items:
        item["name"] = names.get(item.get("prn"))
        for sug in item.get("suggestions") or []:
            sug["name"] = names.get(sug["prn"])
    return items


@router.post("/review/{review_id}/approve", summary="Approve: mark attendance, optionally learn the face")
def approve_review(review_id: str, body: ReviewDecision, user: CurrentUser = Depends(require_staff)) -> dict:
    return ov_service.decide_review(review_id, True, body, user)


@router.post("/review/{review_id}/reject", summary="Reject a low-confidence match")
def reject_review(review_id: str, body: ReviewDecision, user: CurrentUser = Depends(require_staff)) -> dict:
    return ov_service.decide_review(review_id, False, body, user)


@router.get("/snapshots/{snapshot_id}", summary="Annotated photo / face crop (JPEG)",
            response_class=Response)
def snapshot(snapshot_id: str, _: CurrentUser = Depends(require_staff)) -> Response:
    doc = logs_repo.get_snapshot(snapshot_id)
    if not doc:
        raise not_found("Snapshot not found or expired (TTL)", "SNAPSHOT_NOT_FOUND")
    return Response(bytes(doc["image"]), media_type=doc.get("content_type", "image/jpeg"),
                    headers={"Cache-Control": "private, max-age=300"})


# ------------------------------------------------------------------ notifications
@router.get("/notifications", summary="My notifications (MongoDB)")
def notifications(limit: int = Query(30, ge=1, le=200), user: CurrentUser = Depends(get_current_user)) -> dict:
    return {"items": notif_repo.list_for_user(user.user_id, user.role, user.prn, limit),
            "unread": notif_repo.unread_count(user.user_id, user.role, user.prn)}


@router.post("/notifications/read", summary="Mark one (id) or all notifications read")
def mark_read(notification_id: str | None = Query(None, alias="id"),
              user: CurrentUser = Depends(get_current_user)) -> dict:
    return {"updated": notif_repo.mark_read(notification_id, user.user_id, user.role, user.prn)}
