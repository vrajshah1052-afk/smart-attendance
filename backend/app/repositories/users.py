"""MySQL: users (authentication principals) and teachers."""
from __future__ import annotations

from typing import Any

from sqlalchemy.engine import Connection

from app.db.mysql import execute, fetch_all, fetch_one, fetch_scalar

USER_SELECT = """
SELECT u.user_id, u.username, u.password_hash, u.role, u.prn, u.teacher_id, u.is_active,
       u.must_change_password, u.failed_logins, u.locked_until, u.last_login_at, u.created_at,
       (u.locked_until IS NOT NULL AND u.locked_until > NOW()) AS is_locked,
       COALESCE(s.full_name, t.full_name, 'Administrator') AS full_name,
       COALESCE(s.email, t.email, u.username) AS email
  FROM users u
  LEFT JOIN students s ON s.prn = u.prn
  LEFT JOIN teachers t ON t.teacher_id = u.teacher_id
"""


def get_by_username(conn: Connection, username: str) -> dict[str, Any] | None:
    return fetch_one(conn, USER_SELECT + " WHERE u.username = :u", {"u": username})


def get_by_id(conn: Connection, user_id: int) -> dict[str, Any] | None:
    return fetch_one(conn, USER_SELECT + " WHERE u.user_id = :id", {"id": user_id})


def get_by_prn(conn: Connection, prn: str) -> dict[str, Any] | None:
    return fetch_one(conn, USER_SELECT + " WHERE u.prn = :p", {"p": prn})


def create_user(conn: Connection, *, username: str, password_hash: str | None, role: str,
                prn: str | None = None, teacher_id: int | None = None, must_change: bool = False) -> int:
    result = execute(conn, """
        INSERT INTO users (username, password_hash, role, prn, teacher_id, must_change_password)
        VALUES (:u, :h, :r, :p, :t, :m)""",
                     {"u": username, "h": password_hash, "r": role, "p": prn, "t": teacher_id, "m": must_change})
    return int(result.lastrowid)


def set_password(conn: Connection, user_id: int, password_hash: str, must_change: bool = False) -> None:
    execute(conn, """UPDATE users SET password_hash = :h, must_change_password = :m,
                     failed_logins = 0, locked_until = NULL WHERE user_id = :id""",
            {"h": password_hash, "m": must_change, "id": user_id})


def record_login_success(conn: Connection, user_id: int) -> None:
    execute(conn, """UPDATE users SET failed_logins = 0, locked_until = NULL, last_login_at = NOW()
                     WHERE user_id = :id""", {"id": user_id})


def record_login_failure(conn: Connection, user_id: int, max_failures: int, lock_minutes: int) -> None:
    # MySQL evaluates single-table UPDATE assignments left to right, so the
    # IF() below already sees the incremented failed_logins value.
    execute(conn, """
        UPDATE users
           SET failed_logins = LEAST(failed_logins + 1, 255),
               locked_until = IF(failed_logins >= :mx, NOW() + INTERVAL :mins MINUTE, locked_until)
         WHERE user_id = :id""", {"id": user_id, "mx": max_failures, "mins": lock_minutes})


def activate_seeded_accounts(conn: Connection, password_hash: str) -> int:
    """Give seeded demo accounts (password_hash IS NULL) the demo password."""
    return execute(conn, "UPDATE users SET password_hash = :h WHERE password_hash IS NULL AND role <> 'ADMIN'",
                   {"h": password_hash}).rowcount


def admin_exists(conn: Connection, username: str) -> bool:
    return bool(fetch_scalar(conn, "SELECT COUNT(*) FROM users WHERE username = :u", {"u": username}))


# ------------------------------------------------------------------ teachers
def list_teachers(conn: Connection) -> list[dict[str, Any]]:
    return fetch_all(conn, """
        SELECT t.teacher_id, t.employee_code, t.full_name, t.email, t.phone, t.designation, b.code AS branch,
               u.user_id, u.is_active
          FROM teachers t JOIN branches b ON b.branch_id = t.branch_id
          LEFT JOIN users u ON u.teacher_id = t.teacher_id ORDER BY t.full_name""")


def create_teacher(conn: Connection, *, employee_code: str, full_name: str, email: str, phone: str | None,
                   branch_id: int, designation: str) -> int:
    result = execute(conn, """
        INSERT INTO teachers (employee_code, full_name, email, phone, branch_id, designation)
        VALUES (:c, :n, :e, :p, :b, :d)""",
                     {"c": employee_code, "n": full_name, "e": email, "p": phone, "b": branch_id, "d": designation})
    return int(result.lastrowid)


def branch_id(conn: Connection, code: str) -> int | None:
    value = fetch_scalar(conn, "SELECT branch_id FROM branches WHERE code = :c", {"c": code})
    return int(value) if value is not None else None


def teacher_contacts(conn: Connection) -> list[dict[str, Any]]:
    return fetch_all(conn, """
        SELECT t.teacher_id, t.full_name, t.email, u.user_id FROM teachers t
          LEFT JOIN users u ON u.teacher_id = t.teacher_id""")
