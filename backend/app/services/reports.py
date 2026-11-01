"""Report builders + exporters (CSV, Excel, PDF)."""
from __future__ import annotations

import csv
import datetime as dt
import io
from dataclasses import dataclass, field
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.config import get_settings
from app.core.errors import not_found
from app.core.utils import format_time
from app.db.mysql import transaction
from app.repositories import attendance as att_repo
from app.repositories import courses as courses_repo


@dataclass
class Section:
    heading: str
    columns: list[str]
    rows: list[list[Any]]
    highlight: list[bool] = field(default_factory=list)


@dataclass
class Report:
    title: str
    subtitle: str
    filename: str
    summary: list[tuple[str, str]] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)


def _fmt(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, dt.datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, float):
        return round(value, 2)
    return value


def _pct(value: Any) -> str:
    return "-" if value is None else f"{float(value):.2f}%"


# ------------------------------------------------------------------ builders
def student_report(prn: str) -> Report:
    data = att_repo.student_report(prn)
    s, threshold = data["summary"], get_settings().shortage_threshold
    report = Report(
        title=f"Attendance report - {s['full_name']}",
        subtitle=f"PRN {s['prn']} | {s['branch']} year {s['year_of_study']} division {s['division']} "
                 f"| roll {s['roll_no']}",
        filename=f"attendance_{s['prn']}",
        summary=[("Sessions", str(s["total_sessions"])), ("Present", str(s["present_count"])),
                 ("Late", str(s["late_count"])), ("Absent", str(s["absent_count"])),
                 ("Attendance", _pct(s["attendance_pct"])),
                 ("Status", "SHORTAGE" if s["is_shortage"] else "OK")],
    )
    report.sections.append(Section(
        "Per course", ["Code", "Course", "Held", "Present", "Late", "Absent", "Attendance %"],
        [[c["course_code"], c["course_name"], c["sessions_held"], c["present_count"], c["late_count"],
          c["absent_count"], _pct(c["attendance_pct"])] for c in data["courses"]],
        [c["attendance_pct"] is not None and c["sessions_held"] > 0 and c["attendance_pct"] < threshold
         for c in data["courses"]]))
    report.sections.append(Section(
        "History", ["Date", "Time", "Course", "Status", "Method", "Late (min)", "Confidence"],
        [[_fmt(h["session_date"]), format_time(h["start_time"]), h["course_code"],
          h["status"] or ("NOT MARKED" if h["session_status"] == "OPEN" else "ABSENT"), h["method"] or "",
          h["late_minutes"] or "", _fmt(h["confidence"])] for h in data["history"]],
        [h["status"] in (None, "ABSENT") and h["session_status"] == "CLOSED" for h in data["history"]]))
    return report


def course_report(course_id: int) -> Report:
    threshold = get_settings().shortage_threshold
    with transaction() as conn:
        course = courses_repo.get_course(conn, course_id)
        if not course:
            raise not_found("Course not found", "COURSE_NOT_FOUND")
        students = att_repo.course_student_rows(conn, course_id)
        sessions = att_repo.course_sessions(conn, course_id)
    held = [x for x in sessions if x["status"] == "CLOSED"]
    pcts = [st["attendance_pct"] for st in students if st["attendance_pct"] is not None]
    report = Report(
        title=f"{course['code']} - {course['name']}",
        subtitle=f"Coordinator: {course['coordinator'] or '-'} | Semester {course['semester']} | "
                 f"Generated {dt.datetime.now():%Y-%m-%d %H:%M}",
        filename=f"course_{course['code']}",
        summary=[("Enrolled", str(len(students))), ("Sessions held", str(len(held))),
                 ("Average attendance", _pct(sum(pcts) / len(pcts) if pcts else None)),
                 (f"Below {threshold:.0f}%", str(sum(1 for st in students if st["is_shortage"])))],
    )
    report.sections.append(Section(
        "Students", ["Roll", "PRN", "Name", "Held", "Present", "Late", "Absent", "Attendance %", "Shortage"],
        [[st["roll_no"], st["prn"], st["full_name"], st["sessions_held"], st["present_count"], st["late_count"],
          st["absent_count"], _pct(st["attendance_pct"]), "YES" if st["is_shortage"] else ""] for st in students],
        [bool(st["is_shortage"]) for st in students]))
    report.sections.append(Section(
        "Sessions", ["Date", "Start", "End", "Status", "Topic", "Present", "Late", "Absent"],
        [[_fmt(x["session_date"]), format_time(x["start_time"]), format_time(x["end_time"]), x["status"],
          x["topic"] or "", x["present_count"], x["late_count"], x["absent_count"]] for x in sessions]))
    return report


def date_report(day: dt.date) -> Report:
    with transaction() as conn:
        sessions = att_repo.date_sessions(conn, day)
        records = att_repo.date_records(conn, day)
    report = Report(
        title=f"Daily attendance - {day.isoformat()}",
        subtitle=f"{len(sessions)} session(s)",
        filename=f"daily_{day.isoformat()}",
        summary=[("Present", str(sum(x["present_count"] for x in sessions))),
                 ("Late", str(sum(x["late_count"] for x in sessions))),
                 ("Absent", str(sum(x["absent_count"] for x in sessions)))],
    )
    report.sections.append(Section(
        "Sessions", ["Course", "Start", "Teacher", "Status", "Enrolled", "Present", "Late", "Absent"],
        [[x["course_code"], format_time(x["start_time"]), x["teacher_name"] or "", x["status"], x["enrolled"],
          x["present_count"], x["late_count"], x["absent_count"]] for x in sessions]))
    report.sections.append(Section(
        "Records", ["Course", "Start", "Roll", "PRN", "Name", "Status", "Method", "Late (min)", "Marked at"],
        [[r["course_code"], format_time(r["start_time"]), r["roll_no"], r["prn"], r["full_name"], r["status"],
          r["method"], r["late_minutes"] or "", _fmt(r["marked_at"])] for r in records],
        [r["status"] == "ABSENT" for r in records]))
    return report


def shortage_report(course_id: int | None = None) -> Report:
    with transaction() as conn:
        rows = att_repo.shortage_list(conn, course_id)
    threshold = get_settings().shortage_threshold
    report = Report(title=f"Attendance shortage (< {threshold:.0f}%)",
                    subtitle=f"Generated {dt.datetime.now():%Y-%m-%d %H:%M}", filename="shortage_list",
                    summary=[("Rows", str(len(rows))), ("Students", str(len({r['prn'] for r in rows})))])
    report.sections.append(Section(
        "Shortage list", ["PRN", "Name", "E-mail", "Course", "Held", "Present", "Late", "Absent", "Attendance %"],
        [[r["prn"], r["full_name"], r["email"], r["course_code"], r["sessions_held"], r["present_count"],
          r["late_count"], r["absent_count"], _pct(r["attendance_pct"])] for r in rows],
        [True] * len(rows)))
    return report


# ------------------------------------------------------------------ exporters
def to_csv(report: Report) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([report.title])
    writer.writerow([report.subtitle])
    for key, value in report.summary:
        writer.writerow([key, value])
    for section in report.sections:
        writer.writerow([])
        writer.writerow([section.heading])
        writer.writerow(section.columns)
        for row in section.rows:
            writer.writerow([_fmt(v) for v in row])
    return ("﻿" + buf.getvalue()).encode("utf-8")  # BOM so Excel opens UTF-8 correctly


def to_xlsx(report: Report) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws["A1"] = report.title
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = report.subtitle
    for i, (key, value) in enumerate(report.summary, start=4):
        ws.cell(row=i, column=1, value=key).font = Font(bold=True)
        ws.cell(row=i, column=2, value=value)
    ws.column_dimensions["A"].width = 24
    ws.column_dimensions["B"].width = 18

    header_fill = PatternFill("solid", fgColor="1E293B")
    alert_fill = PatternFill("solid", fgColor="FEE2E2")
    for section in report.sections:
        sheet = wb.create_sheet(title="".join(c for c in section.heading if c not in "[]:*?/\\")[:31])
        sheet.append(section.columns)
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center")
        for idx, row in enumerate(section.rows):
            sheet.append([_fmt(v) for v in row])
            if idx < len(section.highlight) and section.highlight[idx]:
                for cell in sheet[sheet.max_row]:
                    cell.fill = alert_fill
        for col_idx, name in enumerate(section.columns, start=1):
            width = max([len(str(name))] + [len(str(_fmt(r[col_idx - 1]))) for r in section.rows[:500]])
            sheet.column_dimensions[get_column_letter(col_idx)].width = min(50, width + 3)
        sheet.freeze_panes = "A2"
        if section.rows:
            sheet.auto_filter.ref = sheet.dimensions
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def to_pdf(report: Report) -> bytes:
    out = io.BytesIO()
    doc = SimpleDocTemplate(out, pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm,
                            topMargin=12 * mm, bottomMargin=12 * mm, title=report.title)
    styles = getSampleStyleSheet()
    cell_style = styles["BodyText"].clone("cell", fontSize=8, leading=10)
    story: list[Any] = [Paragraph(report.title, styles["Title"]), Paragraph(report.subtitle, styles["Normal"]),
                        Spacer(1, 6)]
    if report.summary:
        summary = Table([[k for k, _ in report.summary], [v for _, v in report.summary]], hAlign="LEFT")
        summary.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E2E8F0")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#94A3B8")),
            ("FONTSIZE", (0, 0), (-1, -1), 9), ("PADDING", (0, 0), (-1, -1), 4)]))
        story += [summary, Spacer(1, 10)]
    for section in report.sections:
        story.append(Paragraph(section.heading, styles["Heading2"]))
        if not section.rows:
            story.append(Paragraph("No data", styles["Italic"]))
            continue
        data = [section.columns] + [[Paragraph(str(_fmt(v)), cell_style) for v in row] for row in section.rows]
        table = Table(data, repeatRows=1)
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E293B")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CBD5E1")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]
        for idx, flag in enumerate(section.highlight):
            if flag:
                style.append(("BACKGROUND", (0, idx + 1), (-1, idx + 1), colors.HexColor("#FEE2E2")))
        table.setStyle(TableStyle(style))
        story += [table, Spacer(1, 10)]
    doc.build(story)
    return out.getvalue()


EXPORTERS = {
    "csv": (to_csv, "text/csv; charset=utf-8"),
    "xlsx": (to_xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "pdf": (to_pdf, "application/pdf"),
}
