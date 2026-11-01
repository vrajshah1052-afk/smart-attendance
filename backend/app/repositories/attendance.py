"""MySQL: attendance marking (via stored procedures) and reports (via views)."""
from __future__ import annotations

import datetime as dt
from typing import Any

import pymysql
from sqlalchemy.engine import Connection

from app.core.errors import AppError, translate_db_error
from app.db.mysql import call_procedure, call_procedure_resultsets, fetch_all, fetch_one


def mark_present(conn: Connection, session_id: int, prn: str, method: str, confidence: float | None,
                 marked_by: int | None) -> str:
    conf = round(float(confidence), 4) if confidence is not None else None
    (result,) = call_procedure(conn, "mark_attendance", [session_id, prn, method, conf, marked_by], out_count=1)
    return str(result)


def mark_late(conn: Connection, session_id: int, prn: str, method: str, confidence: float | None,
              marked_by: int | None) -> tuple[int, str]:
    conf = round(float(confidence), 4) if confidence is not None else None
    minutes, result = call_procedure(conn, "mark_late", [session_id, prn, method, conf, marked_by], out_count=2)
    return int(minutes or 0), str(result)


def statuses_for_session(conn: Connection, session_id: int) -> dict[str, str]:
    rows = fetch_all(conn, "SELECT prn, status FROM attendance WHERE session_id = :s", {"s": session_id})
    return {r["prn"]: r["status"] for r in rows}


def get_record(conn: Connection, session_id: int, prn: str) -> dict[str, Any] | None:
    return fetch_one(conn, "SELECT * FROM attendance WHERE session_id = :s AND prn = :p", {"s": session_id, "p": prn})


# ----------------------------------------------------------------- reports
def student_report(prn: str) -> dict[str, Any]:
    """get_student_report() returns 3 result sets: summary, per course, history."""
    try:
        sets = call_procedure_resultsets("get_student_report", [prn])
    except pymysql.err.MySQLError as exc:
        mapped = translate_db_error(exc)
        raise mapped if mapped else exc
    if len(sets) < 3 or not sets[0]:
        raise AppError(404, "STUDENT_NOT_FOUND", "Student not found")
    summary = sets[0][0]
    summary["is_shortage"] = bool(summary.get("is_shortage"))
    return {"summary": summary, "courses": sets[1], "history": sets[2]}


def course_student_rows(conn: Connection, course_id: int) -> list[dict[str, Any]]:
    return fetch_all(conn, """
        SELECT x.prn, x.full_name, s.roll_no, x.sessions_held, x.present_count, x.late_count, x.absent_count,
               x.attendance_pct,
               (x.sessions_held > 0 AND x.attendance_pct <
                 (SELECT CAST(meta_value AS DECIMAL(5,2)) FROM app_meta WHERE meta_key = 'shortage_threshold'))
                 AS is_shortage
          FROM v_student_course_attendance x JOIN students s ON s.prn = x.prn
         WHERE x.course_id = :c ORDER BY s.roll_no, x.prn""", {"c": course_id})


def course_sessions(conn: Connection, course_id: int) -> list[dict[str, Any]]:
    return fetch_all(conn, """SELECT * FROM v_session_summary WHERE course_id = :c
                              ORDER BY session_date DESC, start_time DESC""", {"c": course_id})


def date_sessions(conn: Connection, day: dt.date) -> list[dict[str, Any]]:
    return fetch_all(conn, "SELECT * FROM v_session_summary WHERE session_date = :d ORDER BY start_time",
                     {"d": day})


def date_records(conn: Connection, day: dt.date) -> list[dict[str, Any]]:
    return fetch_all(conn, """
        SELECT ses.session_id, c.code AS course_code, ses.start_time, s.prn, s.full_name, s.roll_no,
               a.status, a.method, a.confidence, a.marked_at, a.late_minutes
          FROM sessions ses
          JOIN courses c ON c.course_id = ses.course_id
          JOIN attendance a ON a.session_id = ses.session_id
          JOIN students s ON s.prn = a.prn
         WHERE ses.session_date = :d
         ORDER BY ses.start_time, c.code, s.roll_no""", {"d": day})


def shortage_list(conn: Connection, course_id: int | None = None) -> list[dict[str, Any]]:
    if course_id:
        return fetch_all(conn, "SELECT * FROM v_shortage_list WHERE course_id = :c ORDER BY attendance_pct",
                         {"c": course_id})
    return fetch_all(conn, "SELECT * FROM v_shortage_list ORDER BY attendance_pct, prn")


def overall_for_students(conn: Connection, prns: list[str]) -> dict[str, dict[str, Any]]:
    if not prns:
        return {}
    rows = fetch_all(conn, "SELECT * FROM v_student_attendance_pct WHERE prn IN :p", {"p": prns})
    return {r["prn"]: r for r in rows}
