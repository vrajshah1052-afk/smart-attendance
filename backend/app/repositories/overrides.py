"""MySQL: manual override workflow + audit log reads."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.engine import Connection

from app.db.mysql import call_procedure, execute, fetch_all, fetch_one, fetch_scalar

OVERRIDE_SELECT = """
SELECT o.*, s.full_name, ses.session_date, ses.start_time, c.code AS course_code, c.name AS course_name,
       ses.course_id, ru.username AS requested_by_username, vu.username AS reviewed_by_username
  FROM override_requests o
  JOIN students s ON s.prn = o.prn
  JOIN sessions ses ON ses.session_id = o.session_id
  JOIN courses c ON c.course_id = ses.course_id
  LEFT JOIN users ru ON ru.user_id = o.requested_by
  LEFT JOIN users vu ON vu.user_id = o.reviewed_by
"""


def create(conn: Connection, *, session_id: int, prn: str, current_status: str | None, requested_status: str,
           late_minutes: int | None, reason: str, requested_by: int) -> int:
    result = execute(conn, """
        INSERT INTO override_requests (session_id, prn, current_status, requested_status, late_minutes, reason,
                                       requested_by)
        VALUES (:s, :p, :c, :r, :l, :reason, :by)""",
                     {"s": session_id, "p": prn, "c": current_status, "r": requested_status, "l": late_minutes,
                      "reason": reason, "by": requested_by})
    return int(result.lastrowid)


def get(conn: Connection, override_id: int) -> dict[str, Any] | None:
    return fetch_one(conn, OVERRIDE_SELECT + " WHERE o.override_id = :id", {"id": override_id})


def list_overrides(conn: Connection, *, status: str | None, prn: str | None, teacher_id: int | None,
                   limit: int = 200) -> list[dict[str, Any]]:
    where = ["1 = 1"]
    params: dict[str, Any] = {"limit": limit}
    if status:
        where.append("o.status = :st")
        params["st"] = status
    if prn:
        where.append("o.prn = :p")
        params["p"] = prn
    if teacher_id:
        where.append("(ses.teacher_id = :t OR c.teacher_id = :t)")
        params["t"] = teacher_id
    return fetch_all(conn, OVERRIDE_SELECT + f" WHERE {' AND '.join(where)} ORDER BY o.created_at DESC LIMIT :limit",
                     params)


def has_pending(conn: Connection, session_id: int, prn: str) -> bool:
    return bool(fetch_scalar(conn, """SELECT COUNT(*) FROM override_requests
                                     WHERE session_id = :s AND prn = :p AND status = 'PENDING'""",
                             {"s": session_id, "p": prn}))


def apply(conn: Connection, override_id: int, reviewer: int, note: str | None) -> None:
    call_procedure(conn, "apply_override", [override_id, reviewer, note])


def reject(conn: Connection, override_id: int, reviewer: int, note: str | None) -> int:
    return execute(conn, """
        UPDATE override_requests SET status = 'REJECTED', reviewed_by = :r, reviewed_at = NOW(), review_note = :n
         WHERE override_id = :id AND status = 'PENDING'""", {"id": override_id, "r": reviewer, "n": note}).rowcount


def list_audit(conn: Connection, *, table: str | None, record_id: str | None, action: str | None,
               limit: int, offset: int) -> list[dict[str, Any]]:
    where = ["1 = 1"]
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if table:
        where.append("a.table_name = :t")
        params["t"] = table
    if record_id:
        where.append("a.record_id = :r")
        params["r"] = record_id
    if action:
        where.append("a.action = :a")
        params["a"] = action
    rows = fetch_all(conn, f"""
        SELECT a.*, u.username AS changed_by_username FROM audit_log a
          LEFT JOIN users u ON u.user_id = a.changed_by
         WHERE {' AND '.join(where)} ORDER BY a.audit_id DESC LIMIT :limit OFFSET :offset""", params)
    for row in rows:
        for key in ("old_values", "new_values"):
            if isinstance(row.get(key), str):
                try:
                    row[key] = json.loads(row[key])
                except ValueError:
                    pass
    return rows
