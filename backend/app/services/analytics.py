"""Dashboard analytics: SQL aggregates (MySQL) + aggregation pipelines (MongoDB)."""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from pymongo.errors import PyMongoError

from app.config import get_settings
from app.core.utils import format_time, local_today, local_tz
from app.db.mysql import fetch_all, fetch_one, transaction
from app.repositories import embeddings as emb_repo
from app.repositories import logs as logs_repo
from app.repositories import notifications as notif_repo
from app.repositories import students as students_repo
from app.services import face_service

logger = logging.getLogger(__name__)


def _safe_mongo(fn: Any, default: Any) -> Any:
    try:
        return fn()
    except PyMongoError as exc:
        logger.warning("analytics: MongoDB part skipped (%s)", exc)
        return default


def summary() -> dict[str, Any]:
    today = local_today()
    with transaction() as conn:
        counts = fetch_one(conn, """
            SELECT (SELECT COUNT(*) FROM students) AS students,
                   (SELECT COUNT(*) FROM students WHERE face_status = 'ENROLLED') AS enrolled_faces,
                   (SELECT COUNT(*) FROM courses WHERE is_active) AS courses,
                   (SELECT COUNT(*) FROM teachers) AS teachers,
                   (SELECT COUNT(*) FROM sessions WHERE session_date = :d) AS sessions_today,
                   (SELECT COUNT(*) FROM sessions WHERE status = 'OPEN') AS sessions_open,
                   (SELECT COUNT(*) FROM sessions WHERE status = 'CLOSED') AS sessions_held,
                   (SELECT COUNT(DISTINCT prn) FROM v_shortage_list) AS shortage_students,
                   (SELECT COUNT(*) FROM override_requests WHERE status = 'PENDING') AS pending_overrides,
                   (SELECT COUNT(*) FROM attendance a JOIN sessions s ON s.session_id = a.session_id
                     WHERE s.session_date = :d AND a.status IN ('PRESENT', 'LATE')) AS marked_today
        """, {"d": today}) or {}
        overall = fetch_one(conn, """
            SELECT ROUND(100 * SUM(a.status IN ('PRESENT','LATE')) / NULLIF(COUNT(*), 0), 2) AS pct
              FROM attendance a JOIN sessions s ON s.session_id = a.session_id WHERE s.status = 'CLOSED'""") or {}
    start_of_day = dt.datetime.combine(today, dt.time.min, tzinfo=local_tz()).astimezone(dt.timezone.utc)
    counts.update({
        "overall_attendance_pct": overall.get("pct"),
        "spoof_today": _safe_mongo(lambda: notif_repo.spoof_count_since(start_of_day), None),
        "unknown_today": _safe_mongo(lambda: logs_repo.unknown_faces_count(start_of_day), None),
        "embeddings": _safe_mongo(emb_repo.total_count, None),
        "pending_reviews": _safe_mongo(notif_repo.pending_review_count, None),
        "shortage_threshold": get_settings().shortage_threshold,
        "engine": face_service.engine_status(),
    })
    return counts


def daily_trend(days: int = 30) -> list[dict[str, Any]]:
    with transaction() as conn:
        rows = fetch_all(conn, """
            SELECT s.session_date AS day, COUNT(DISTINCT s.session_id) AS sessions,
                   COALESCE(SUM(a.status = 'PRESENT'), 0) AS present,
                   COALESCE(SUM(a.status = 'LATE'), 0) AS late,
                   COALESCE(SUM(a.status = 'ABSENT'), 0) AS absent
              FROM sessions s LEFT JOIN attendance a ON a.session_id = s.session_id
             WHERE s.status = 'CLOSED' AND s.session_date >= CURDATE() - INTERVAL :days DAY
             GROUP BY s.session_date ORDER BY s.session_date""", {"days": days})
    for r in rows:
        total = r["present"] + r["late"] + r["absent"]
        r["pct"] = round(100 * (r["present"] + r["late"]) / total, 2) if total else None
        r["day"] = r["day"].isoformat()
    return rows


def course_wise() -> list[dict[str, Any]]:
    with transaction() as conn:
        return fetch_all(conn, "SELECT * FROM v_course_summary ORDER BY code")


def heatmap(weeks: int = 12) -> dict[str, Any]:
    with transaction() as conn:
        calendar = fetch_all(conn, """
            SELECT s.session_date AS day, COUNT(DISTINCT s.session_id) AS sessions,
                   ROUND(100 * SUM(a.status IN ('PRESENT','LATE')) / NULLIF(COUNT(a.attendance_id), 0), 2) AS pct
              FROM sessions s LEFT JOIN attendance a ON a.session_id = s.session_id
             WHERE s.status = 'CLOSED' AND s.session_date >= CURDATE() - INTERVAL :w WEEK
             GROUP BY s.session_date ORDER BY s.session_date""", {"w": weeks})
        slots = fetch_all(conn, """
            SELECT WEEKDAY(s.session_date) AS weekday, HOUR(s.start_time) AS hour,
                   COUNT(DISTINCT s.session_id) AS sessions,
                   ROUND(100 * SUM(a.status IN ('PRESENT','LATE')) / NULLIF(COUNT(a.attendance_id), 0), 2) AS pct
              FROM sessions s LEFT JOIN attendance a ON a.session_id = s.session_id
             WHERE s.status = 'CLOSED' AND s.session_date >= CURDATE() - INTERVAL :w WEEK
             GROUP BY WEEKDAY(s.session_date), HOUR(s.start_time) ORDER BY weekday, hour""", {"w": weeks})
    for c in calendar:
        c["day"] = c["day"].isoformat()
    return {"calendar": calendar, "weekday_hour": slots, "weeks": weeks}


def top_bottom(limit: int = 5) -> dict[str, list[dict[str, Any]]]:
    sql = """SELECT prn, full_name, branch, division, attendance_pct, total_sessions, present_count, late_count,
                    absent_count FROM v_student_attendance_pct WHERE total_sessions > 0
              ORDER BY attendance_pct {order}, prn LIMIT :n"""
    with transaction() as conn:
        top = fetch_all(conn, sql.format(order="DESC"), {"n": limit})
        bottom = fetch_all(conn, sql.format(order="ASC"), {"n": limit})
    return {"top": top, "bottom": bottom}


def spoof_per_day(days: int = 30) -> list[dict[str, Any]]:
    return _safe_mongo(lambda: notif_repo.spoof_per_day(days, get_settings().timezone), [])


def recognition_stats(days: int = 30) -> list[dict[str, Any]]:
    return _safe_mongo(lambda: logs_repo.daily_recognition_stats(days, get_settings().timezone), [])


def low_confidence(days: int = 30, limit: int = 20) -> list[dict[str, Any]]:
    s = get_settings()
    rows = _safe_mongo(lambda: logs_repo.low_confidence_matches(days, limit, face_service.match_threshold(),
                                                                s.low_conf_margin), [])
    if rows:
        with transaction() as conn:
            names = students_repo.names_for(conn, [r["prn"] for r in rows])
        for r in rows:
            r["name"] = names.get(r["prn"])
    return rows


def todays_sessions() -> list[dict[str, Any]]:
    with transaction() as conn:
        rows = fetch_all(conn, "SELECT * FROM v_session_summary WHERE session_date = :d ORDER BY start_time",
                         {"d": local_today()})
    for r in rows:
        r["start_time"], r["end_time"] = format_time(r["start_time"]), format_time(r["end_time"])
    return rows


def recent_spoofs(limit: int = 10) -> list[dict[str, Any]]:
    return _safe_mongo(lambda: notif_repo.recent_spoofs(limit), [])
