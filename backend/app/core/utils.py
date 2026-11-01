"""Small helpers shared across layers."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from app.config import get_settings


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
