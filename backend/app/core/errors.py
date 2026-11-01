"""Domain errors and translation of database errors into HTTP responses."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pymongo.errors import ConnectionFailure, PyMongoError, ServerSelectionTimeoutError
from sqlalchemy.exc import DBAPIError, InterfaceError

from app.logging_config import request_id_var

logger = logging.getLogger(__name__)


class AppError(Exception):
    """An error that maps 1:1 to an HTTP response."""

    def __init__(self, status_code: int, code: str, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def bad_request(message: str, code: str = "BAD_REQUEST", details: Any = None) -> AppError:
    return AppError(400, code, message, details)


def forbidden(message: str = "You are not allowed to do this", code: str = "FORBIDDEN") -> AppError:
    return AppError(403, code, message)


def not_found(message: str, code: str = "NOT_FOUND") -> AppError:
    return AppError(404, code, message)


def conflict(message: str, code: str = "CONFLICT", details: Any = None) -> AppError:
    return AppError(409, code, message, details)


def unprocessable(message: str, code: str = "UNPROCESSABLE", details: Any = None) -> AppError:
    return AppError(422, code, message, details)


def unavailable(message: str, code: str = "SERVICE_UNAVAILABLE") -> AppError:
    return AppError(503, code, message)


# SIGNAL SQLSTATE '45000' message -> (http status, human message)
SIGNAL_MAP: dict[str, tuple[int, str]] = {
    "SESSION_NOT_FOUND": (404, "Session not found"),
    "SESSION_NOT_OPEN": (409, "Session is not open for attendance"),
    "STUDENT_NOT_ENROLLED": (400, "Student is not enrolled in this course"),
    "STUDENT_NOT_FOUND": (404, "Student not found"),
    "ALREADY_MARKED": (409, "Attendance is already marked for this session"),
    "OUTSIDE_SESSION_WINDOW": (409, "Session can only be opened inside its time window"),
    "INVALID_SESSION_STATE": (409, "Session is not in a state that allows this action"),
    "OVERRIDE_NOT_FOUND": (404, "Override request not found"),
    "OVERRIDE_ALREADY_RESOLVED": (409, "Override request was already resolved"),
    "USER_ROLE_LINK_INVALID": (400, "User role does not match its linked profile"),
}

_CONNECTION_ERRNOS = {2002, 2003, 2005, 2006, 2013, 2026, 2055, 1040, 1045, 1049}


def _mysql_errno(exc: BaseException) -> tuple[int | None, str]:
    orig = getattr(exc, "orig", exc)
    args = getattr(orig, "args", ())
    errno = args[0] if args and isinstance(args[0], int) else None
    message = str(args[1]) if len(args) > 1 else str(orig)
    return errno, message


def translate_db_error(exc: BaseException) -> AppError | None:
    """Map a MySQL error to an AppError (None if it is an unexpected bug)."""
    errno, message = _mysql_errno(exc)
    if errno == 1644:  # SIGNAL from a stored program
        key, _, extra = message.partition(":")
        status, human = SIGNAL_MAP.get(key, (400, key))
        details = {"existing_status": extra} if extra else None
        if extra:
            human = f"{human} ({extra})"
        return AppError(status, key, human, details)
    if errno == 1062:
        return conflict("Duplicate entry: this record already exists", "DUPLICATE_ENTRY", {"db": message})
    if errno in (1451, 1452):
        return bad_request("Referenced record does not exist or is still in use", "FOREIGN_KEY_VIOLATION",
                           {"db": message})
    if errno == 3819:
        return bad_request("A data rule (CHECK constraint) was violated", "CHECK_VIOLATION", {"db": message})
    if errno in (1205, 1213):
        return conflict("The database is busy, please retry", "DB_LOCK_TIMEOUT")
    if errno in _CONNECTION_ERRNOS or isinstance(exc, InterfaceError):
        return unavailable("MySQL is unavailable, please try again shortly", "MYSQL_UNAVAILABLE")
    return None


def _payload(code: str, message: str, details: Any = None) -> dict[str, Any]:
    body: dict[str, Any] = {"detail": message, "code": code, "request_id": request_id_var.get()}
    if details is not None:
        body["details"] = details
    return body


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=_payload(exc.code, exc.message, exc.details))

    @app.exception_handler(DBAPIError)
    async def _db_error(_: Request, exc: DBAPIError) -> JSONResponse:
        mapped = translate_db_error(exc)
        if mapped is None:
            logger.exception("Unhandled MySQL error", exc_info=exc)
            return JSONResponse(status_code=500, content=_payload("DB_ERROR", "Unexpected database error"))
        if mapped.status_code >= 500:
            logger.error("MySQL unavailable: %s", exc)
        return JSONResponse(status_code=mapped.status_code, content=_payload(mapped.code, mapped.message, mapped.details))

    @app.exception_handler(PyMongoError)
    async def _mongo_error(_: Request, exc: PyMongoError) -> JSONResponse:
        if isinstance(exc, (ServerSelectionTimeoutError, ConnectionFailure)):
            logger.error("MongoDB unavailable: %s", exc)
            return JSONResponse(status_code=503, content=_payload(
                "MONGO_UNAVAILABLE", "MongoDB is unavailable, please try again shortly"))
        logger.exception("Unhandled MongoDB error", exc_info=exc)
        return JSONResponse(status_code=500, content=_payload("MONGO_ERROR", "Unexpected document-store error"))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error", exc_info=exc)
        return JSONResponse(status_code=500, content=_payload("INTERNAL_ERROR", "Internal server error"))


__all__ = [
    "AppError", "bad_request", "forbidden", "not_found", "conflict", "unprocessable", "unavailable",
    "translate_db_error", "register_exception_handlers",
]
