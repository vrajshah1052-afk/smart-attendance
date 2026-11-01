"""Background jobs (APScheduler): auto-close sessions, saga recovery, e-mails."""
from __future__ import annotations

import logging
from typing import Any, Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import get_settings
from app.db.mysql import transaction
from app.repositories import sessions as sessions_repo
from app.services.email import send_daily_summaries, send_shortage_alerts
from app.services.notify import event
from app.services.privacy import recover_sagas

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def auto_close_sessions() -> int:
    with transaction() as conn:
        closed = sessions_repo.auto_close_expired(conn, get_settings().auto_close_grace_min)
    if closed:
        logger.info("Auto-closed %d expired session(s)", closed)
        event("sessions_auto_closed", {"count": closed})
    return closed


def _guard(name: str, fn: Callable[[], Any]) -> Callable[[], None]:
    def runner() -> None:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - a failing job must not kill the scheduler
            logger.error("Job %s failed: %s", name, exc)

    return runner


JOBS: dict[str, Callable[[], Any]] = {
    "auto_close_sessions": auto_close_sessions,
    "recover_sagas": recover_sagas,
    "daily_summary": send_daily_summaries,
    "shortage_alerts": send_shortage_alerts,
}


def start_scheduler() -> None:
    global _scheduler
    s = get_settings()
    if not s.scheduler_enabled or _scheduler is not None:
        return
    sched = BackgroundScheduler(timezone=s.timezone, job_defaults={"coalesce": True, "max_instances": 1})
    sched.add_job(_guard("auto_close_sessions", auto_close_sessions), "interval", minutes=5, id="auto_close")
    sched.add_job(_guard("recover_sagas", recover_sagas), "interval", minutes=10, id="recover_sagas")
    sched.add_job(_guard("daily_summary", send_daily_summaries),
                  CronTrigger(hour=s.daily_summary_hour, minute=0, timezone=s.timezone), id="daily_summary")
    sched.add_job(_guard("shortage_alerts", send_shortage_alerts),
                  CronTrigger(day_of_week=s.shortage_alert_day, hour=s.shortage_alert_hour, minute=0,
                              timezone=s.timezone), id="shortage_alerts")
    sched.start()
    _scheduler = sched
    logger.info("Scheduler started with jobs: %s", [j.id for j in sched.get_jobs()])


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
