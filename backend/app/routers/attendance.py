"""Attendance: group photo, confirm, late entry, QR, reports per student / course / date."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile

from app.config import get_settings
from app.core.deps import CurrentUser, assert_student_scope, get_current_user, require_staff, require_student
from app.core.errors import not_found
from app.db.mysql import transaction
from app.face.imageio import read_upload
from app.repositories import attendance as att_repo
from app.repositories import courses as courses_repo
from app.schemas.attendance import GroupConfirmRequest, QRMarkRequest
from app.services import attendance as att_service
from app.services.challenges import issue_challenge

router = APIRouter(tags=["attendance"])


@router.get("/liveness/challenge", summary="Get a one-time liveness challenge (blink / head turn)")
def liveness_challenge(user: CurrentUser = Depends(require_staff)) -> dict:
    return issue_challenge(user.user_id)


@router.post("/attendance/group", summary="Step 1: analyse a class photo (no DB write to attendance)")
def group_attendance(session_id: int = Form(...), photo: UploadFile = File(...),
                     threshold: float | None = Form(None, ge=0.2, le=0.95),
                     actor: CurrentUser = Depends(require_staff)) -> dict:
    data = read_upload(photo, get_settings().max_upload_bytes * 2)
    return att_service.analyse_group(session_id, data, actor, threshold)


@router.post("/attendance/group/confirm", summary="Step 2: teacher-confirmed list saved atomically")
def confirm_group(body: GroupConfirmRequest, actor: CurrentUser = Depends(require_staff)) -> dict:
    return att_service.confirm_group(body.draft_id, body.session_id, body.prns,
                                     [m.model_dump() for m in body.manual], actor)


@router.post("/attendance/late", summary="Solo late entry with liveness (marks LATE + minutes)")
def late_attendance(request: Request, session_id: int = Form(...), frames: list[UploadFile] = File(...),
                    challenge_token: str | None = Form(None),
                    actor: CurrentUser = Depends(require_staff)) -> dict:
    max_bytes = get_settings().max_upload_bytes
    data = [read_upload(f, max_bytes) for f in frames]
    client_ip = request.client.host if request.client else None
    return att_service.late_entry(session_id, data, challenge_token, actor, client_ip)


@router.post("/attendance/qr", summary="QR fallback: student submits the rotating session code")
def qr_attendance(body: QRMarkRequest, user: CurrentUser = Depends(require_student)) -> dict:
    return att_service.qr_mark(body.session_id, body.code, user)


@router.get("/attendance/student/{prn}", summary="Per-student report (stored procedure get_student_report)")
def student_attendance(prn: str, user: CurrentUser = Depends(get_current_user)) -> dict:
    prn = prn.upper()
    assert_student_scope(user, prn)
    return att_repo.student_report(prn)


@router.get("/attendance/course/{course_id}", summary="Per-course report with shortage flags")
def course_attendance(course_id: int, _: CurrentUser = Depends(require_staff)) -> dict:
    with transaction() as conn:
        course = courses_repo.get_course(conn, course_id)
        if not course:
            raise not_found("Course not found", "COURSE_NOT_FOUND")
        students = att_repo.course_student_rows(conn, course_id)
        sessions = att_repo.course_sessions(conn, course_id)
    for st in students:
        st["is_shortage"] = bool(st["is_shortage"])
    return {"course": course, "students": students, "sessions": sessions,
            "shortage_threshold": get_settings().shortage_threshold}


@router.get("/attendance/date/{day}", summary="Per-date report")
def date_attendance(day: dt.date, _: CurrentUser = Depends(require_staff)) -> dict:
    with transaction() as conn:
        return {"date": day.isoformat(), "sessions": att_repo.date_sessions(conn, day),
                "records": att_repo.date_records(conn, day)}


@router.get("/attendance/session/{session_id}", summary="Live roster of one session")
def session_attendance(session_id: int, user: CurrentUser = Depends(require_staff)) -> dict:
    return att_service.session_roster(session_id, user)


@router.get("/attendance/shortage", summary="Students below the shortage threshold (v_shortage_list)")
def shortage(course_id: int | None = Query(None), _: CurrentUser = Depends(require_staff)) -> dict:
    with transaction() as conn:
        rows = att_repo.shortage_list(conn, course_id)
    return {"threshold": get_settings().shortage_threshold, "items": rows}
