"""Exports (CSV / Excel / PDF) and analytics endpoints."""
from __future__ import annotations

import datetime as dt
from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from app.core.deps import CurrentUser, assert_student_scope, get_current_user, require_staff
from app.core.errors import bad_request, forbidden
from app.services import analytics
from app.services import reports as reports_service

router = APIRouter(tags=["reports"])


@router.get("/reports/export", summary="Export a report as CSV, Excel or PDF",
            response_class=Response,
            responses={200: {"content": {"text/csv": {}, "application/pdf": {},
                                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {}}}})
def export(
    type: Literal["csv", "xlsx", "pdf"] = Query("csv", description="csv | xlsx | pdf"),  # noqa: A002
    scope: Literal["student", "course", "date", "shortage"] = Query("student"),
    prn: str | None = None,
    course_id: int | None = None,
    day: dt.date | None = Query(None, alias="date"),
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    if scope == "student":
        if not prn:
            if not user.prn:
                raise bad_request("prn is required for a student report", "PRN_REQUIRED")
            prn = user.prn
        prn = prn.upper()
        assert_student_scope(user, prn)
        report = reports_service.student_report(prn)
    else:
        if not user.is_staff:
            raise forbidden("Only staff can export class reports")
        if scope == "course":
            if not course_id:
                raise bad_request("course_id is required", "COURSE_REQUIRED")
            report = reports_service.course_report(course_id)
        elif scope == "date":
            report = reports_service.date_report(day or dt.date.today())
        else:
            report = reports_service.shortage_report(course_id)
    exporter, media_type = reports_service.EXPORTERS[type]
    return Response(exporter(report), media_type=media_type,
                    headers={"Content-Disposition": f'attachment; filename="{report.filename}.{type}"'})


# ------------------------------------------------------------------ analytics
@router.get("/analytics/summary", summary="Dashboard KPIs")
def summary(_: CurrentUser = Depends(require_staff)) -> dict:
    return analytics.summary()


@router.get("/analytics/daily-trend", summary="Attendance % per day (closed sessions)")
def daily_trend(days: int = Query(30, ge=1, le=365), _: CurrentUser = Depends(require_staff)) -> list[dict]:
    return analytics.daily_trend(days)


@router.get("/analytics/course-wise", summary="Average attendance per course (v_course_summary)")
def course_wise(_: CurrentUser = Depends(require_staff)) -> list[dict]:
    return analytics.course_wise()


@router.get("/analytics/heatmap", summary="Calendar + weekday x hour attendance heatmap")
def heatmap(weeks: int = Query(12, ge=1, le=52), _: CurrentUser = Depends(require_staff)) -> dict:
    return analytics.heatmap(weeks)


@router.get("/analytics/top-bottom", summary="Top and bottom attendees")
def top_bottom(limit: int = Query(5, ge=1, le=50), _: CurrentUser = Depends(require_staff)) -> dict:
    return analytics.top_bottom(limit)


@router.get("/analytics/spoof-per-day", summary="Spoof attempts per day (MongoDB aggregation)")
def spoof_per_day(days: int = Query(30, ge=1, le=365), _: CurrentUser = Depends(require_staff)) -> list[dict]:
    return analytics.spoof_per_day(days)


@router.get("/analytics/recognition-stats", summary="Daily recognition statistics (MongoDB aggregation)")
def recognition_stats(days: int = Query(30, ge=1, le=365), _: CurrentUser = Depends(require_staff)) -> list[dict]:
    return analytics.recognition_stats(days)


@router.get("/analytics/low-confidence", summary="Students with frequent low-confidence matches")
def low_confidence(days: int = Query(30, ge=1, le=365), limit: int = Query(20, ge=1, le=200),
                   _: CurrentUser = Depends(require_staff)) -> list[dict]:
    return analytics.low_confidence(days, limit)


@router.get("/analytics/today", summary="Today's sessions")
def today(_: CurrentUser = Depends(require_staff)) -> list[dict]:
    return analytics.todays_sessions()


@router.get("/analytics/recent-spoofs", summary="Latest spoof attempts")
def recent_spoofs(limit: int = Query(10, ge=1, le=100), _: CurrentUser = Depends(require_staff)) -> list[dict]:
    return analytics.recent_spoofs(limit)
