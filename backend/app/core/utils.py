"""Small helpers shared across layers."""
from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from app.config import get_settings


# A username is an e-mail only when it has an @ AND a dot after it. Employee
# codes look like VIT@001, so the @ on its own cannot decide this.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalise_username(username: str) -> str:
    """Fold a login name to the form it is stored in.

    E-mails are lower-cased; everything else (PRNs, employee codes such as
    VIT@001) is upper-cased, so the sign-in box is case-insensitive either way.
    """
    username = (username or "").strip()
    return username.lower() if _EMAIL_RE.match(username) else username.upper()


def hour_slot(now: dt.datetime | dt.time) -> tuple[dt.time, dt.time]:
    """The one-hour slot a moment falls in: 09:06 -> (09:00, 10:00).

    The last slot of the day ends at 23:59:59 so a lecture never spills onto the
    next date.
    """
    hour = now.hour
    if hour == 23:
        return dt.time(23, 0), dt.time(23, 59, 59)
    return dt.time(hour, 0), dt.time(hour + 1, 0)


def slot_hour(value: Any) -> int:
    """Hour of a start_time however the driver hands it over (TIME -> timedelta)."""
    if isinstance(value, dt.timedelta):
        return int(value.total_seconds()) // 3600
    if isinstance(value, dt.time):
        return value.hour
    return int(str(value)[:2])


def slot_label(hour: int) -> str:
    return f"{hour:02d}:00-23:59" if hour == 23 else f"{hour:02d}:00-{hour + 1:02d}:00"


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def local_tz() -> ZoneInfo:
    return ZoneInfo(get_settings().timezone)


def local_today() -> dt.date:
    return dt.datetime.now(local_tz()).date()


def format_time(value: Any) -> str | None:
    """MySQL TIME comes back from PyMySQL as timedelta."""
    if value is None:
        return None
    if isinstance(value, dt.timedelta):
        total = int(value.total_seconds())
        return f"{total // 3600:02d}:{(total % 3600) // 60:02d}"
    if isinstance(value, dt.time):
        return value.strftime("%H:%M")
    return str(value)[:5]


def normalize_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dt.timedelta):
        return format_time(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {k: normalize_value(v) for k, v in row.items()}


def to_builtin(obj: Any) -> Any:
    """Convert numpy scalars/arrays (not BSON-encodable) to Python builtins."""
    if isinstance(obj, dict):
        return {str(k): to_builtin(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_builtin(v) for v in obj]
    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, Decimal):
        return float(obj)
    return obj


def mask_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return email
    user, domain = email.split("@", 1)
    return f"{user[:2]}***@{domain}"
