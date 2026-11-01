"""Single-service deploy (Render): one process serves the API under /api, the
live feed under /ws and the built React app (FRONTEND_DIST) everywhere else.

    FRONTEND_DIST=/app/static uvicorn app.serve:app

In docker compose nginx does this routing; in development the Vite proxy does.
"""
from __future__ import annotations

from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.responses import FileResponse, Response
from starlette.staticfiles import StaticFiles
from starlette.types import Receive, Scope, Send

from app.config import get_settings
from app.main import app as api


class SinglePageApp(StaticFiles):
    """Static files; any other path gets index.html so client-side routes (/join/K7Q2MX) load."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            response = FileResponse(Path(str(self.directory)) / "index.html")
        if path.startswith("assets/"):  # content-hashed by Vite
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-cache"
        return response


def _frontend() -> SinglePageApp:
    dist = get_settings().frontend_dist
    if not dist or not (Path(dist) / "index.html").is_file():
        raise RuntimeError(f"FRONTEND_DIST must point to the built frontend (npm run build), got {dist!r}")
    return SinglePageApp(directory=dist)


frontend = _frontend()


async def app(scope: Scope, receive: Receive, send: Send) -> None:
    path = scope.get("path", "")
    if scope["type"] == "lifespan" or path.startswith("/ws/"):
        await api(scope, receive, send)
    elif path == "/api" or path.startswith("/api/"):
        # same contract as the nginx / Vite proxy: /api/students -> /students (root_path keeps /docs working)
        await api({**scope, "root_path": scope.get("root_path", "") + "/api"}, receive, send)
    else:
        await frontend(scope, receive, send)
