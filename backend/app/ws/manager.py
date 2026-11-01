"""WebSocket connection manager for the real-time live feed.

`publish()` is thread-safe: services running in FastAPI's thread pool push
events onto the event loop with run_coroutine_threadsafe.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket

from app.core.deps import CurrentUser
from app.core.utils import to_builtin, utcnow

logger = logging.getLogger(__name__)


@dataclass
class ClientState:
    user: CurrentUser
    session_id: int | None = None
    course_id: int | None = None
    roster: dict[str, str] = field(default_factory=dict)
    roster_loaded_at: float = 0.0
    draft_id: str | None = None
    seen: dict[str, float] = field(default_factory=dict)
    busy: bool = False


class LiveManager:
    def __init__(self) -> None:
        self._clients: dict[WebSocket, ClientState] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def connect(self, ws: WebSocket, user: CurrentUser) -> ClientState:
        state = ClientState(user=user)
        self._clients[ws] = state
        logger.info("WS connected: %s (%s) - %d clients", user.username, user.role, len(self._clients))
        return state

    async def disconnect(self, ws: WebSocket) -> None:
        self._clients.pop(ws, None)

    async def _send(self, ws: WebSocket, payload: dict[str, Any]) -> None:
        try:
            await ws.send_json(payload)
        except Exception:  # noqa: BLE001 - dead socket
            self._clients.pop(ws, None)

    async def broadcast(self, payload: dict[str, Any], prn: str | None = None, staff_only: bool = False) -> None:
        targets = []
        for ws, state in list(self._clients.items()):
            if state.user.is_staff:
                targets.append(ws)
            elif not staff_only and prn and state.user.prn == prn:
                targets.append(ws)
        await asyncio.gather(*(self._send(ws, payload) for ws in targets), return_exceptions=True)

    def publish(self, event: str, data: dict[str, Any], prn: str | None = None, staff_only: bool = False) -> None:
        """Fire-and-forget from any thread."""
        if self._loop is None or self._loop.is_closed() or not self._clients:
            return
        payload = {"type": event, "data": to_builtin(data), "ts": utcnow().isoformat()}
        coro = self.broadcast(payload, prn=prn, staff_only=staff_only)
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self._loop:
            self._loop.create_task(coro)
        else:
            asyncio.run_coroutine_threadsafe(coro, self._loop)


live_manager = LiveManager()
