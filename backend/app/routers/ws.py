"""WS /ws/live - real-time recognition feed + server events.

Client -> server messages:
  {"type": "ping"}
  {"type": "subscribe", "session_id": 12}
  {"type": "frame", "session_id": 12, "image": "data:image/jpeg;base64,..."}   (staff only)
Server -> client: {"type": "recognition" | "notification" | "attendance_committed" | "late_marked" | ...}
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from app.core.deps import user_from_token
from app.core.errors import AppError
from app.services.attendance import live_frame
from app.ws.manager import live_manager

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/live")
async def live_socket(ws: WebSocket, token: str | None = Query(None)) -> None:
    try:
        user = user_from_token(token or "")
    except AppError:
        await ws.close(code=4401)
        return
    await ws.accept()
    state = await live_manager.connect(ws, user)
    await ws.send_json({"type": "hello", "data": {"user": user.username, "role": user.role}})
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except ValueError:
                await ws.send_json({"type": "error", "data": {"detail": "invalid JSON"}})
                continue
            kind = msg.get("type")
            if kind == "ping":
                await ws.send_json({"type": "pong"})
            elif kind == "subscribe":
                state.session_id = None
                await ws.send_json({"type": "subscribed", "data": {"session_id": msg.get("session_id")}})
            elif kind == "frame":
                if not user.is_staff:
                    await ws.send_json({"type": "error", "data": {"detail": "staff only"}})
                    continue
                if state.busy:  # back-pressure: drop frames while one is processing
                    continue
                state.busy = True
                try:
                    result = await run_in_threadpool(live_frame, state, int(msg.get("session_id", 0)),
                                                     str(msg.get("image", "")))
                    await ws.send_json(result)
                except AppError as exc:
                    await ws.send_json({"type": "error", "data": {"detail": exc.message, "code": exc.code}})
                except Exception as exc:  # noqa: BLE001
                    logger.exception("live frame failed")
                    await ws.send_json({"type": "error", "data": {"detail": str(exc)}})
                finally:
                    state.busy = False
            else:
                await ws.send_json({"type": "error", "data": {"detail": f"unknown message type {kind!r}"}})
    except WebSocketDisconnect:
        pass
    finally:
        await live_manager.disconnect(ws)
