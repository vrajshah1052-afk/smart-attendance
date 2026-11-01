"""Notification fan-out: MongoDB (persistent inbox) + WebSocket (real time)."""
from __future__ import annotations

from typing import Any

from app.repositories import notifications as notif_repo
from app.ws.manager import live_manager


def notify(type_: str, title: str, message: str, *, recipient_prn: str | None = None,
           recipient_user_id: int | None = None, audience_role: str | None = None,
           data: dict[str, Any] | None = None) -> None:
    doc = notif_repo.create_notification(type_=type_, title=title, message=message, recipient_prn=recipient_prn,
                                         recipient_user_id=recipient_user_id, audience_role=audience_role, data=data)
    payload = doc or {"type": type_, "title": title, "message": message, "data": data or {}}
    staff_only = recipient_prn is None and audience_role in ("ADMIN", "TEACHER")
    live_manager.publish("notification", payload, prn=recipient_prn, staff_only=staff_only)


def event(name: str, data: dict[str, Any], prn: str | None = None, staff_only: bool = True) -> None:
    """Real-time only (no inbox entry)."""
    live_manager.publish(name, data, prn=prn, staff_only=staff_only)
