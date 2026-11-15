"""MySQL: class sessions (open/close time window)."""
from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy.engine import Connection

from app.db.mysql import call_procedure, execute, fetch_all, fetch_one, fetch_scalar


def get_session(conn: Connection, session_id: int) -> dict[str, Any] | None:
    return fetch_one(conn, "SELECT * FROM v_session_summary WHERE session_id = :id", {"id": session_id})


def list_sessions(conn: Connection, *, course_id: int | None = None, day: dt.date | None = None,
                  date_from: dt.date | None = None, date_to: dt.date | None = None, status: str | None = None,
                  teacher_id: int | None = None, limit: int = 200) -> list[dict[str, Any]]:
    where = ["1 = 1"]
    params: dict[str, Any] = {"limit": limit}
    if course_id:
        where.append("course_id = :cid")
        params["cid"] = course_id
    if day:
        where.append("session_date = :day")
        params["day"] = day
    if date_from:
        where.append("session_date >= :df")
        params["df"] = date_from
    if date_to:
        where.append("session_date <= :dt")
        params["dt"] = date_to
    if status:
        where.append("status = :st")
        params["st"] = status
    if teacher_id:
        where.append("(teacher_id = :tid OR course_id IN (SELECT course_id FROM courses WHERE teacher_id = :tid))")
        params["tid"] = teacher_id
    return fetch_all(conn, f"""SELECT * FROM v_session_summary WHERE {' AND '.join(where)}
                               ORDER BY session_date DESC, start_time DESC LIMIT :limit""", params)


def db_now(conn: Connection) -> dt.datetime:
    """The database clock: attendance timestamps come from the same NOW()."""
    return fetch_one(conn, "SELECT NOW() AS now")["now"]


def find_by_slot(conn: Connection, course_id: int, day: dt.date, start: dt.time) -> dict[str, Any] | None:
    return fetch_one(conn, """
        SELECT * FROM sessions
         WHERE course_id = :c AND session_date = :d AND start_time = :s""",
                     {"c": course_id, "d": day, "s": start})


def create_session(conn: Connection, data: dict[str, Any]) -> int:
    result = execute(conn, """
        INSERT INTO sessions (course_id, teacher_id, session_date, start_time, end_time, late_after_min, room, topic)
        VALUES (:course_id, :teacher_id, :session_date, :start_time, :end_time, :late_after_min, :room, :topic)""",
                     data)
    return int(result.lastrowid)


def open_session(conn: Connection, session_id: int, force: bool, early_min: int) -> None:
    call_procedure(conn, "open_session", [session_id, force, early_min])


def close_session(conn: Connection, session_id: int, closed_by: int | None) -> int:
    (absent,) = call_procedure(conn, "close_session", [session_id, closed_by], out_count=1)
    return int(absent or 0)


def cancel_session(conn: Connection, session_id: int) -> int:
    return execute(conn, "UPDATE sessions SET status = 'CANCELLED' WHERE session_id = :id AND status = 'SCHEDULED'",
                   {"id": session_id}).rowcount


def auto_close_expired(conn: Connection, grace_min: int) -> int:
    (closed,) = call_procedure(conn, "auto_close_expired_sessions", [grace_min], out_count=1)
    return int(closed or 0)


def can_manage(conn: Connection, session_id: int, teacher_id: int | None) -> bool:
    if teacher_id is None:
        return False
    return bool(fetch_scalar(conn, """
        SELECT COUNT(*) FROM sessions s JOIN courses c ON c.course_id = s.course_id
         WHERE s.session_id = :sid AND (s.teacher_id = :tid OR c.teacher_id = :tid)""",
                             {"sid": session_id, "tid": teacher_id}))


def is_enrolled(conn: Connection, session_id: int, prn: str) -> bool:
    return bool(fetch_scalar(conn, """
        SELECT COUNT(*) FROM sessions s JOIN enrollments e ON e.course_id = s.course_id
         WHERE s.session_id = :sid AND e.prn = :p""", {"sid": session_id, "p": prn}))


def roster_with_status(conn: Connection, session_id: int) -> list[dict[str, Any]]:
    return fetch_all(conn, """
        SELECT s.prn, s.full_name, s.roll_no, s.face_status, d.name AS division,
               a.status, a.method, a.confidence, a.marked_at, a.late_minutes
          FROM sessions ses
          JOIN enrollments e ON e.course_id = ses.course_id
          JOIN students s ON s.prn = e.prn
          JOIN divisions d ON d.division_id = s.division_id
          LEFT JOIN attendance a ON a.session_id = ses.session_id AND a.prn = s.prn
         WHERE ses.session_id = :sid
         ORDER BY d.year_of_study, d.name, s.roll_no, s.prn""", {"sid": session_id})


def todays_sessions_by_teacher(conn: Connection, day: dt.date) -> list[dict[str, Any]]:
    return fetch_all(conn, "SELECT * FROM v_session_summary WHERE session_date = :d ORDER BY teacher_id, start_time",
                     {"d": day})
