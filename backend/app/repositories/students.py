"""MySQL: students, divisions, enrollments."""
from __future__ import annotations

from typing import Any

from sqlalchemy.engine import Connection

from app.db.mysql import execute, fetch_all, fetch_one, fetch_scalar

STUDENT_SELECT = """
SELECT s.prn, s.full_name, s.email, s.phone, s.roll_no, s.face_status, s.consent_given, s.consent_at,
       s.created_at, s.updated_at, d.division_id, d.name AS division, d.year_of_study AS year,
       b.code AS branch, b.name AS branch_name
  FROM students s
  JOIN divisions d ON d.division_id = s.division_id
  JOIN branches b  ON b.branch_id = d.branch_id
"""


def get_student(conn: Connection, prn: str) -> dict[str, Any] | None:
    return fetch_one(conn, STUDENT_SELECT + " WHERE s.prn = :prn", {"prn": prn})


def exists(conn: Connection, prn: str) -> bool:
    return bool(fetch_scalar(conn, "SELECT COUNT(*) FROM students WHERE prn = :prn", {"prn": prn}))


def email_taken(conn: Connection, email: str, exclude_prn: str | None = None) -> bool:
    return bool(fetch_scalar(
        conn, "SELECT COUNT(*) FROM students WHERE email = :e AND prn <> COALESCE(:x, '')",
        {"e": email, "x": exclude_prn}))


def roll_taken(conn: Connection, division_id: int, roll_no: int, exclude_prn: str | None = None) -> bool:
    return bool(fetch_scalar(
        conn,
        "SELECT COUNT(*) FROM students WHERE division_id = :d AND roll_no = :r AND prn <> COALESCE(:x, '')",
        {"d": division_id, "r": roll_no, "x": exclude_prn}))


def find_division(conn: Connection, branch_code: str, year: int, division: str) -> dict[str, Any] | None:
    return fetch_one(conn, """
        SELECT d.division_id, d.branch_id
          FROM divisions d JOIN branches b ON b.branch_id = d.branch_id
         WHERE b.code = :b AND d.year_of_study = :y AND d.name = :n""",
                     {"b": branch_code, "y": year, "n": division})


def division_names(conn: Connection, branch_id: int, year: int) -> list[str]:
    return [r["name"] for r in fetch_all(conn, """
        SELECT name FROM divisions WHERE branch_id = :b AND year_of_study = :y ORDER BY name""",
                                         {"b": branch_id, "y": year})]


def insert_student(conn: Connection, data: dict[str, Any]) -> None:
    execute(conn, """
        INSERT INTO students (prn, full_name, email, phone, division_id, roll_no, consent_given, consent_at, face_status)
        VALUES (:prn, :full_name, :email, :phone, :division_id, :roll_no, TRUE, NOW(), :face_status)""",
            {**data, "face_status": data.get("face_status", "PENDING")})


def update_student(conn: Connection, prn: str, fields: dict[str, Any]) -> int:
    allowed = {"full_name", "email", "phone", "division_id", "roll_no"}
    sets = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not sets:
        return 0
    clause = ", ".join(f"{k} = :{k}" for k in sets)
    return execute(conn, f"UPDATE students SET {clause} WHERE prn = :prn", {**sets, "prn": prn}).rowcount


def set_face_status(conn: Connection, prn: str, status: str) -> None:
    execute(conn, "UPDATE students SET face_status = :s WHERE prn = :p", {"s": status, "p": prn})


def delete_student(conn: Connection, prn: str) -> int:
    return execute(conn, "DELETE FROM students WHERE prn = :p", {"p": prn}).rowcount


def auto_enroll(conn: Connection, prn: str, branch_id: int, year: int) -> int:
    """Enrol into all active courses of the student's branch and year."""
    return execute(conn, """
        INSERT INTO enrollments (prn, course_id)
        SELECT :prn, c.course_id FROM courses c
         WHERE c.branch_id = :b AND c.year_of_study = :y AND c.is_active = TRUE
           AND NOT EXISTS (SELECT 1 FROM enrollments e WHERE e.prn = :prn AND e.course_id = c.course_id)""",
                   {"prn": prn, "b": branch_id, "y": year}).rowcount


def enrolled_courses(conn: Connection, prn: str) -> list[dict[str, Any]]:
    return fetch_all(conn, """
        SELECT c.course_id, c.code, c.name, e.enrolled_at FROM enrollments e
          JOIN courses c ON c.course_id = e.course_id WHERE e.prn = :p ORDER BY c.code""", {"p": prn})


def list_students(conn: Connection, *, search: str | None, branch: str | None, year: int | None,
                  division: str | None, face_status: str | None, course_id: int | None,
                  limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
    where = ["1 = 1"]
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if search:
        where.append("(s.prn LIKE :q OR s.full_name LIKE :q OR s.email LIKE :q)")
        params["q"] = f"%{search}%"
    if branch:
        where.append("b.code = :branch")
        params["branch"] = branch
    if year:
        where.append("d.year_of_study = :year")
        params["year"] = year
    if division:
        where.append("d.name = :division")
        params["division"] = division
    if face_status:
        where.append("s.face_status = :fs")
        params["fs"] = face_status
    if course_id:
        where.append("EXISTS (SELECT 1 FROM enrollments e WHERE e.prn = s.prn AND e.course_id = :cid)")
        params["cid"] = course_id
    clause = " AND ".join(where)
    total = fetch_scalar(conn, f"""
        SELECT COUNT(*) FROM students s JOIN divisions d ON d.division_id = s.division_id
          JOIN branches b ON b.branch_id = d.branch_id WHERE {clause}""", params)
    rows = fetch_all(conn, STUDENT_SELECT + f" WHERE {clause} ORDER BY b.code, d.year_of_study, d.name, s.roll_no"
                                            " LIMIT :limit OFFSET :offset", params)
    return rows, int(total or 0)


def names_for(conn: Connection, prns: list[str]) -> dict[str, str]:
    if not prns:
        return {}
    rows = fetch_all(conn, "SELECT prn, full_name FROM students WHERE prn IN :prns", {"prns": prns})
    return {r["prn"]: r["full_name"] for r in rows}


def course_roster(conn: Connection, course_id: int) -> list[dict[str, Any]]:
    return fetch_all(conn, """
        SELECT s.prn, s.full_name, s.roll_no, s.face_status, s.email, d.name AS division
          FROM enrollments e JOIN students s ON s.prn = e.prn
          JOIN divisions d ON d.division_id = s.division_id
         WHERE e.course_id = :c ORDER BY d.year_of_study, d.name, s.roll_no, s.prn""", {"c": course_id})


def academic_structure(conn: Connection) -> list[dict[str, Any]]:
    return fetch_all(conn, """
        SELECT b.branch_id, b.code, b.name, d.division_id, d.year_of_study, d.name AS division
          FROM branches b JOIN divisions d ON d.branch_id = b.branch_id
         ORDER BY b.code, d.year_of_study, d.name""")


def list_pending_approval(conn: Connection) -> list[dict[str, Any]]:
    return fetch_all(conn, """
        SELECT s.prn, s.full_name, s.email, s.phone, s.roll_no, s.face_status, s.created_at,
               d.name AS division, d.year_of_study AS year, b.code AS branch
          FROM students s
          JOIN divisions d ON d.division_id = s.division_id
          JOIN branches b ON b.branch_id = d.branch_id
         WHERE s.face_status = 'PENDING_APPROVAL'
         ORDER BY s.created_at""")
