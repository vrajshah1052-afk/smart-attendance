"""MySQL: courses and enrollments."""
from __future__ import annotations

import secrets
from typing import Any

from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from app.db.mysql import execute, fetch_all, fetch_one, fetch_scalar


def list_courses(conn: Connection, teacher_id: int | None = None, active_only: bool = True) -> list[dict[str, Any]]:
    where = ["1 = 1"]
    params: dict[str, Any] = {}
    if active_only:
        where.append("c.is_active = TRUE")
    if teacher_id is not None:
        where.append("""(c.teacher_id = :t OR EXISTS (SELECT 1 FROM sessions s
                         WHERE s.course_id = c.course_id AND s.teacher_id = :t))""")
        params["t"] = teacher_id
    return fetch_all(conn, f"""
        SELECT c.course_id, c.code, c.name, c.credits, c.year_of_study, c.semester, c.teacher_id,
               b.code AS branch, v.coordinator, v.enrolled, v.sessions_held, v.avg_attendance_pct, v.shortage_count
          FROM courses c
          JOIN branches b ON b.branch_id = c.branch_id
          JOIN v_course_summary v ON v.course_id = c.course_id
         WHERE {' AND '.join(where)} ORDER BY c.code""", params)


def get_course(conn: Connection, course_id: int) -> dict[str, Any] | None:
    return fetch_one(conn, """
        SELECT c.course_id, c.code, c.name, c.credits, c.year_of_study, c.semester, c.teacher_id, c.branch_id,
               b.code AS branch, t.full_name AS coordinator
          FROM courses c JOIN branches b ON b.branch_id = c.branch_id
          LEFT JOIN teachers t ON t.teacher_id = c.teacher_id WHERE c.course_id = :id""", {"id": course_id})


def create_course(conn: Connection, data: dict[str, Any]) -> int:
    result = execute(conn, """
        INSERT INTO courses (code, name, credits, branch_id, year_of_study, semester, teacher_id)
        VALUES (:code, :name, :credits, :branch_id, :year_of_study, :semester, :teacher_id)""", data)
    return int(result.lastrowid)


def enroll(conn: Connection, course_id: int, prns: list[str]) -> int:
    count = 0
    for prn in prns:
        count += execute(conn, """
            INSERT INTO enrollments (prn, course_id)
            SELECT :p, :c FROM DUAL
             WHERE EXISTS (SELECT 1 FROM students WHERE prn = :p)
               AND NOT EXISTS (SELECT 1 FROM enrollments WHERE prn = :p AND course_id = :c)""",
                         {"p": prn, "c": course_id}).rowcount
    return count


def is_coordinator(conn: Connection, course_id: int, teacher_id: int) -> bool:
    return bool(fetch_scalar(conn, "SELECT COUNT(*) FROM courses WHERE course_id = :c AND teacher_id = :t",
                             {"c": course_id, "t": teacher_id}))


# ------------------------------------------------------------------ class codes
# no 0/O or 1/I/L: the code is read off a projector and typed on a phone
JOIN_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
JOIN_CODE_LENGTH = 6

JOIN_SELECT = """
    SELECT c.course_id, c.code, c.name, c.credits, c.year_of_study, c.semester, c.branch_id, c.teacher_id,
           c.join_code, c.join_open, b.code AS branch, b.name AS branch_name, t.full_name AS coordinator,
           (SELECT COUNT(*) FROM enrollments e WHERE e.course_id = c.course_id) AS enrolled
      FROM courses c JOIN branches b ON b.branch_id = c.branch_id
      LEFT JOIN teachers t ON t.teacher_id = c.teacher_id"""


def normalise_join_code(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


def join_info(conn: Connection, course_id: int) -> dict[str, Any] | None:
    return fetch_one(conn, JOIN_SELECT + " WHERE c.course_id = :id", {"id": course_id})


def get_by_join_code(conn: Connection, code: str) -> dict[str, Any] | None:
    return fetch_one(conn, JOIN_SELECT + " WHERE c.join_code = :code AND c.is_active = TRUE", {"code": code})


def new_join_code(conn: Connection, course_id: int) -> str:
    """Give the course a fresh class code (the old QR stops working)."""
    for _ in range(5):
        code = "".join(secrets.choice(JOIN_ALPHABET) for _ in range(JOIN_CODE_LENGTH))
        try:
            execute(conn, "UPDATE courses SET join_code = :code WHERE course_id = :id", {"code": code, "id": course_id})
            return code
        except IntegrityError:  # another course already has it: draw again
            continue
    raise RuntimeError("Could not allocate a unique class code")


def ensure_join_code(conn: Connection, course_id: int) -> None:
    if fetch_scalar(conn, "SELECT join_code FROM courses WHERE course_id = :id", {"id": course_id}) is None:
        new_join_code(conn, course_id)


def set_join_open(conn: Connection, course_id: int, is_open: bool) -> None:
    execute(conn, "UPDATE courses SET join_open = :o WHERE course_id = :id", {"o": is_open, "id": course_id})
