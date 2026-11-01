"""SMTP e-mail + the two automated jobs (shortage alerts, teacher daily summary)."""
from __future__ import annotations

import datetime as dt
import html
import logging
import smtplib
import ssl
from collections import defaultdict
from email.message import EmailMessage
from typing import Any

from app.config import get_settings
from app.core.utils import format_time, local_today, local_tz
from app.db.mysql import transaction
from app.repositories import attendance as att_repo
from app.repositories import logs as logs_repo
from app.repositories import notifications as notif_repo
from app.repositories import sessions as sessions_repo
from app.repositories import users as users_repo
from app.services.notify import notify

logger = logging.getLogger(__name__)


def send_email(to: str, subject: str, html_body: str, text_body: str | None = None) -> str:
    """Returns SENT | DRY_RUN | FAILED (never raises)."""
    s = get_settings()
    if not s.email_enabled or not s.smtp_host:
        logger.info("[email dry-run] to=%s subject=%s", to, subject)
        return "DRY_RUN"
    msg = EmailMessage()
    msg["From"] = s.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text_body or "Please view this e-mail in an HTML capable client.")
    msg.add_alternative(html_body, subtype="html")
    try:
        if s.smtp_ssl:
            with smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=10, context=ssl.create_default_context()) as smtp:
                if s.smtp_user:
                    smtp.login(s.smtp_user, s.smtp_password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=10) as smtp:
                if s.smtp_starttls:
                    smtp.starttls(context=ssl.create_default_context())
                if s.smtp_user:
                    smtp.login(s.smtp_user, s.smtp_password)
                smtp.send_message(msg)
        return "SENT"
    except (OSError, smtplib.SMTPException) as exc:
        logger.error("E-mail to %s failed: %s", to, exc)
        return "FAILED"


def _layout(title: str, body: str) -> str:
    return f"""<div style="font-family:Segoe UI,Arial,sans-serif;max-width:640px;margin:auto;color:#0f172a">
      <div style="background:#0f172a;color:#fff;padding:16px 20px;border-radius:10px 10px 0 0">
        <strong>Smart Attendance</strong> &middot; {html.escape(title)}</div>
      <div style="border:1px solid #e2e8f0;border-top:0;padding:20px;border-radius:0 0 10px 10px">{body}
      <p style="color:#64748b;font-size:12px;margin-top:24px">Automated message - do not reply.</p></div></div>"""


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    head = "".join(f"<th style='text-align:left;padding:6px;border-bottom:2px solid #cbd5e1'>{html.escape(h)}</th>"
                   for h in headers)
    body = "".join("<tr>" + "".join(f"<td style='padding:6px;border-bottom:1px solid #e2e8f0'>{html.escape(str(c))}"
                                    "</td>" for c in r) + "</tr>" for r in rows)
    return f"<table style='border-collapse:collapse;width:100%;font-size:14px'><tr>{head}</tr>{body}</table>"


# ------------------------------------------------------------------ jobs
def send_shortage_alerts(force: bool = False) -> dict[str, int]:
    s = get_settings()
    with transaction() as conn:
        rows = att_repo.shortage_list(conn)
    by_student: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_student[r["prn"]].append(r)
    stats = {"students": len(by_student), "sent": 0, "dry_run": 0, "failed": 0, "skipped": 0}
    for prn, courses in by_student.items():
        if not force and notif_repo.recently_notified("SHORTAGE", prn, days=6):
            stats["skipped"] += 1
            continue
        first = courses[0]
        body = (f"<p>Dear {html.escape(first['full_name'])},</p><p>Your attendance is below the required "
                f"<b>{s.shortage_threshold:.0f}%</b> in the following course(s):</p>"
                + _table(["Course", "Held", "Attended", "Attendance"],
                         [[f"{c['course_code']} {c['course_name']}", c["sessions_held"],
                           c["present_count"] + c["late_count"], f"{c['attendance_pct']:.2f}%"] for c in courses])
                + "<p>Please meet your course coordinator. Students below the threshold may be detained "
                  "from end-semester examinations.</p>")
        status = send_email(first["email"], "Attendance shortage alert", _layout("Attendance shortage", body))
        stats[{"SENT": "sent", "DRY_RUN": "dry_run", "FAILED": "failed"}[status]] += 1
        notify("SHORTAGE", "Attendance shortage",
               "Below {:.0f}% in: {}".format(s.shortage_threshold, ", ".join(
                   f"{c['course_code']} ({c['attendance_pct']:.1f}%)" for c in courses)),
               recipient_prn=prn, data={"courses": [c["course_code"] for c in courses], "email_status": status})
    logger.info("Shortage alerts: %s", stats)
    return stats


def send_daily_summaries(day: dt.date | None = None) -> dict[str, int]:
    day = day or local_today()
    with transaction() as conn:
        sessions = sessions_repo.todays_sessions_by_teacher(conn, day)
        teachers = {t["teacher_id"]: t for t in users_repo.teacher_contacts(conn)}
    by_teacher: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for x in sessions:
        if x["teacher_id"]:
            by_teacher[int(x["teacher_id"])].append(x)
    start = dt.datetime.combine(day, dt.time.min, tzinfo=local_tz()).astimezone(dt.timezone.utc)
    stats = {"teachers": len(by_teacher), "sent": 0, "dry_run": 0, "failed": 0}
    for teacher_id, items in by_teacher.items():
        teacher = teachers.get(teacher_id)
        if not teacher:
            continue
        try:
            unknown = logs_repo.unknown_faces_count(start, [int(i["session_id"]) for i in items])
        except Exception:  # noqa: BLE001
            unknown = 0
        body = (f"<p>Hello {html.escape(teacher['full_name'])}, here is your summary for <b>{day}</b>.</p>"
                + _table(["Course", "Time", "Status", "Present", "Late", "Absent", "Enrolled"],
                         [[i["course_code"], format_time(i["start_time"]), i["status"], i["present_count"],
                           i["late_count"], i["absent_count"], i["enrolled"]] for i in items])
                + f"<p>Unknown faces flagged today: <b>{unknown}</b></p>")
        status = send_email(teacher["email"], f"Daily attendance summary - {day}", _layout("Daily summary", body))
        stats[{"SENT": "sent", "DRY_RUN": "dry_run", "FAILED": "failed"}[status]] += 1
        if teacher.get("user_id"):
            notify("DAILY_SUMMARY", f"Daily summary {day}",
                   f"{len(items)} session(s), {sum(i['present_count'] + i['late_count'] for i in items)} attended, "
                   f"{unknown} unknown face(s).", recipient_user_id=int(teacher["user_id"]),
                   data={"day": day.isoformat(), "email_status": status})
    logger.info("Daily summaries: %s", stats)
    return stats
