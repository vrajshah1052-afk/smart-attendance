"""Courses, sessions (open/close window, QR) and academic structure."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Query

from app.config import get_settings
from app.core.deps import CurrentUser, get_current_user, require_admin, require_staff
from app.core.errors import bad_request, conflict, forbidden, not_found
from app.core.security import generate_temp_password, hash_password, validate_password_strength
from app.core.utils import format_time, normalise_username
from app.db.mysql import transaction
from app.repositories import courses as courses_repo
from app.repositories import sessions as sessions_repo
from app.repositories import students as students_repo
from app.repositories import users as users_repo
from app.schemas.academic import (CourseCreate, EnrollRequest, SessionCreate, SessionNow, SessionOpen,
                                  TeacherCreate, TeacherPassword)
from app.services.attendance import assert_can_manage, load_session
from app.services.challenges import qr_payload
from app.services.notify import event, notify

router = APIRouter(tags=["academic"])


def _session_out(row: dict) -> dict:
    row["start_time"], row["end_time"] = format_time(row["start_time"]), format_time(row["end_time"])
    return row


def hour_slot(now: dt.datetime) -> tuple[dt.time, dt.time]:
    """The one-hour slot `now` falls in: 08:43 -> (08:00, 09:00).

    The last hour of the day ends at 23:59:59 so the window stays on one date.
    """
    start = now.replace(minute=0, second=0, microsecond=0)
    if start.hour == 23:
        return start.time(), dt.time(23, 59, 59)
    return start.time(), (start + dt.timedelta(hours=1)).time()


# ------------------------------------------------------------------ meta
@router.get("/meta/academic", summary="Branches and divisions (for forms)")
def academic(_: CurrentUser = Depends(get_current_user)) -> dict:
    with transaction() as conn:
        rows = students_repo.academic_structure(conn)
    branches: dict[str, dict] = {}
    for r in rows:
        b = branches.setdefault(r["code"], {"code": r["code"], "name": r["name"], "divisions": {}})
        b["divisions"].setdefault(str(r["year_of_study"]), []).append(r["division"])
    return {"branches": list(branches.values())}


# ------------------------------------------------------------------ courses
@router.get("/courses", summary="Courses with live summary (v_course_summary)")
def list_courses(mine: bool = False, user: CurrentUser = Depends(require_staff)) -> list[dict]:
    with transaction() as conn:
        return courses_repo.list_courses(conn, teacher_id=user.teacher_id if mine and user.teacher_id else None)


@router.post("/courses", status_code=201, summary="Create a course (admin)")
def create_course(body: CourseCreate, _: CurrentUser = Depends(require_admin)) -> dict:
    with transaction() as conn:
        branch_id = users_repo.branch_id(conn, body.branch.upper())
        if branch_id is None:
            raise bad_request("Unknown branch", "UNKNOWN_BRANCH")
        course_id = courses_repo.create_course(conn, {**body.model_dump(exclude={"branch"}), "branch_id": branch_id,
                                                      "code": body.code.upper()})
        return courses_repo.get_course(conn, course_id) or {}


@router.get("/courses/{course_id}/students", summary="Course roster")
def course_students(course_id: int, _: CurrentUser = Depends(require_staff)) -> list[dict]:
    with transaction() as conn:
        if not courses_repo.get_course(conn, course_id):
            raise not_found("Course not found", "COURSE_NOT_FOUND")
        return students_repo.course_roster(conn, course_id)


@router.post("/courses/{course_id}/enroll", summary="Enrol students into a course")
def enroll(course_id: int, body: EnrollRequest, user: CurrentUser = Depends(require_staff)) -> dict:
    with transaction() as conn:
        if not courses_repo.get_course(conn, course_id):
            raise not_found("Course not found", "COURSE_NOT_FOUND")
        if not user.is_admin and not courses_repo.is_coordinator(conn, course_id, user.teacher_id or -1):
            raise forbidden("Only the course coordinator or an admin can enrol students")
        added = courses_repo.enroll(conn, course_id, [p.strip().upper() for p in body.prns])
    return {"course_id": course_id, "enrolled": added}


# ------------------------------------------------------------------ teachers
@router.get("/teachers", summary="Teachers")
def list_teachers(_: CurrentUser = Depends(require_staff)) -> list[dict]:
    with transaction() as conn:
        return users_repo.list_teachers(conn)


@router.post("/teachers", status_code=201,
             summary="Create teacher + login (admin only; teachers never register themselves)")
def create_teacher(body: TeacherCreate, _: CurrentUser = Depends(require_admin)) -> dict:
    """Only an admin makes a teacher account, and the admin picks the password.

    The employee code is the username: a teacher signs in with the code, not an
    e-mail. Leaving the password out generates a one-time one the teacher must
    change on first login.
    """
    password = body.password or generate_temp_password()
    validate_password_strength(password)
    username = normalise_username(body.employee_code)
    with transaction() as conn:
        branch_id = users_repo.branch_id(conn, body.branch.upper())
        if branch_id is None:
            raise bad_request("Unknown branch", "UNKNOWN_BRANCH")
        if users_repo.get_by_username(conn, username):
            raise conflict(f"Employee code {username} is already taken", "EMPLOYEE_CODE_EXISTS")
        teacher_id = users_repo.create_teacher(conn, employee_code=username, full_name=body.full_name,
                                               email=body.email.lower(), phone=body.phone, branch_id=branch_id,
                                               designation=body.designation)
        users_repo.create_user(conn, username=username, password_hash=hash_password(password),
                               role="TEACHER", teacher_id=teacher_id, must_change=body.password is None)
    return {"teacher_id": teacher_id, "username": username,
            "temp_password": None if body.password else password}


@router.post("/teachers/{teacher_id}/password", summary="Set or reset a teacher's password (admin)")
def set_teacher_password(teacher_id: int, body: TeacherPassword, _: CurrentUser = Depends(require_admin)) -> dict:
    """Teachers cannot register themselves, so an admin must be able to reset a
    forgotten password. The teacher can change it again from their account."""
    password = body.password or generate_temp_password()
    validate_password_strength(password)
    with transaction() as conn:
        user = users_repo.user_by_teacher_id(conn, teacher_id)
        if not user:
            raise not_found("This teacher has no login", "TEACHER_LOGIN_NOT_FOUND")
        users_repo.set_password(conn, int(user["user_id"]), hash_password(password),
                                must_change=body.password is None)
        username = user["username"]
    return {"teacher_id": teacher_id, "username": username,
            "temp_password": None if body.password else password}


# ------------------------------------------------------------------ sessions
@router.get("/sessions", summary="List sessions (filters: course, date range, status)")
def list_sessions(course_id: int | None = None, day: dt.date | None = Query(None, alias="date"),
                  date_from: dt.date | None = None, date_to: dt.date | None = None, status: str | None = None,
                  mine: bool = False, user: CurrentUser = Depends(require_staff)) -> list[dict]:
    with transaction() as conn:
        rows = sessions_repo.list_sessions(conn, course_id=course_id, day=day, date_from=date_from, date_to=date_to,
                                           status=status.upper() if status else None,
                                           teacher_id=user.teacher_id if mine else None)
    return [_session_out(r) for r in rows]


@router.post("/sessions", status_code=201, summary="Create a session (optionally open it now)")
def create_session(body: SessionCreate, user: CurrentUser = Depends(require_staff)) -> dict:
    s = get_settings()
    with transaction() as conn:
        course = courses_repo.get_course(conn, body.course_id)
        if not course:
            raise not_found("Course not found", "COURSE_NOT_FOUND")
        teacher_id = body.teacher_id if user.is_admin and body.teacher_id else user.teacher_id
        if not user.is_admin and course["teacher_id"] != user.teacher_id and teacher_id != user.teacher_id:
            raise forbidden()
        session_id = sessions_repo.create_session(conn, {
            "course_id": body.course_id, "teacher_id": teacher_id or course["teacher_id"],
            "session_date": body.session_date, "start_time": body.start_time, "end_time": body.end_time,
            "late_after_min": body.late_after_min, "room": body.room, "topic": body.topic})
        if body.open_now:
            sessions_repo.open_session(conn, session_id, force=not s.session_window_enforced,
                                       early_min=s.session_open_early_min)
        session = sessions_repo.get_session(conn, session_id)
    return _session_out(session or {"session_id": session_id})


@router.post("/sessions/now", status_code=201,
             summary="Start a lecture now: the session covers the clock hour you are in")
def create_session_now(body: SessionNow, user: CurrentUser = Depends(require_staff)) -> dict:
    """A lecture started at 08:43 is recorded as the 08:00-09:00 slot.

    The clock comes from MySQL, the same one the attendance rows are stamped
    with. Starting the same course twice in one hour reopens that slot instead
    of colliding with the (course, date, start_time) unique key.
    """
    s = get_settings()
    with transaction() as conn:
        course = courses_repo.get_course(conn, body.course_id)
        if not course:
            raise not_found("Course not found", "COURSE_NOT_FOUND")
        teacher_id = body.teacher_id if user.is_admin and body.teacher_id else user.teacher_id
        if not user.is_admin and course["teacher_id"] != user.teacher_id and teacher_id != user.teacher_id:
            raise forbidden()
        now = sessions_repo.db_now(conn)
        start, end = hour_slot(now)
        existing = sessions_repo.find_by_slot(conn, body.course_id, now.date(), start)
        if existing:
            session_id = int(existing["session_id"])
            if existing["status"] == "SCHEDULED":
                sessions_repo.open_session(conn, session_id, force=True, early_min=s.session_open_early_min)
        else:
            session_id = sessions_repo.create_session(conn, {
                "course_id": body.course_id, "teacher_id": teacher_id or course["teacher_id"],
                "session_date": now.date(), "start_time": start, "end_time": end,
                "late_after_min": body.late_after_min, "room": body.room, "topic": body.topic})
            sessions_repo.open_session(conn, session_id, force=True, early_min=s.session_open_early_min)
        session = sessions_repo.get_session(conn, session_id)
    event("session_opened", {"session_id": session_id, "course_code": course["code"]})
    return _session_out(session or {"session_id": session_id})


@router.get("/sessions/{session_id}", summary="Session details")
def get_session(session_id: int, _: CurrentUser = Depends(require_staff)) -> dict:
    with transaction() as conn:
        return _session_out(load_session(conn, session_id))


@router.post("/sessions/{session_id}/open", summary="Open the attendance window (procedure open_session)")
def open_session(session_id: int, body: SessionOpen | None = None, user: CurrentUser = Depends(require_staff)) -> dict:
    s = get_settings()
    force = bool(body and body.force)
    with transaction() as conn:
        session = load_session(conn, session_id)
        assert_can_manage(conn, session, user)
        sessions_repo.open_session(conn, session_id, force=force or not s.session_window_enforced,
                                   early_min=s.session_open_early_min)
        session = load_session(conn, session_id)
    event("session_opened", {"session_id": session_id, "course_code": session["course_code"]})
    return _session_out(session)


@router.post("/sessions/{session_id}/close", summary="Close: unmarked students become ABSENT (procedure)")
def close_session(session_id: int, user: CurrentUser = Depends(require_staff)) -> dict:
    with transaction() as conn:
        session = load_session(conn, session_id)
        assert_can_manage(conn, session, user)
        absent = sessions_repo.close_session(conn, session_id, user.user_id)
        session = load_session(conn, session_id)
    event("session_closed", {"session_id": session_id, "absent_marked": absent})
    if user.user_id:
        notify("SESSION", "Session closed", f"{session['course_code']} {session['session_date']}: "
               f"{session['present_count']} present, {session['late_count']} late, {absent} absent.",
               recipient_user_id=user.user_id, data={"session_id": session_id})
    return {"session": _session_out(session), "absent_marked": absent}


@router.post("/sessions/{session_id}/cancel", summary="Cancel a scheduled session")
def cancel_session(session_id: int, user: CurrentUser = Depends(require_staff)) -> dict:
    with transaction() as conn:
        session = load_session(conn, session_id)
        assert_can_manage(conn, session, user)
        if not sessions_repo.cancel_session(conn, session_id):
            raise conflict("Only scheduled sessions can be cancelled", "INVALID_SESSION_STATE")
        return _session_out(load_session(conn, session_id))


@router.get("/sessions/{session_id}/qr", summary="Rotating QR code (fallback when face recognition fails)")
def session_qr(session_id: int, user: CurrentUser = Depends(require_staff)) -> dict:
    with transaction() as conn:
        session = load_session(conn, session_id)
        assert_can_manage(conn, session, user)
    if session["status"] != "OPEN":
        raise conflict("Open the session to display its QR code", "SESSION_NOT_OPEN")
    return qr_payload(session_id)
