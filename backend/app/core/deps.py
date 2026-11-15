"""FastAPI dependencies: authentication and role-based authorisation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer

from app.core.errors import AppError, forbidden
from app.core.security import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

ADMIN = "ADMIN"
TEACHER = "TEACHER"
STUDENT = "STUDENT"
STAFF = (ADMIN, TEACHER)


@dataclass(frozen=True)
class CurrentUser:
    user_id: int
    username: str
    role: str
    prn: str | None = None
    teacher_id: int | None = None
    full_name: str | None = None

    @property
    def is_staff(self) -> bool:
        return self.role in STAFF

    @property
    def is_admin(self) -> bool:
        return self.role == ADMIN


# Actor recorded in the audit trail / saga log for sign-ups nobody on staff made.
SELF_SIGNUP = CurrentUser(user_id=None, username="self-registration", role=STUDENT)  # type: ignore[arg-type]


def user_from_token(token: str) -> CurrentUser:
    payload = decode_token(token)
    try:
        return CurrentUser(
            user_id=int(payload["sub"]),
            username=str(payload.get("username", "")),
            role=str(payload["role"]),
            prn=payload.get("prn"),
            teacher_id=payload.get("teacher_id"),
            full_name=payload.get("name"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AppError(401, "TOKEN_INVALID", "Malformed token") from exc


def get_current_user(token: str | None = Depends(oauth2_scheme)) -> CurrentUser:
    if not token:
        raise AppError(401, "NOT_AUTHENTICATED", "Not authenticated")
    return user_from_token(token)


def require_roles(*roles: str) -> Callable[[CurrentUser], CurrentUser]:
    def _dependency(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in roles:
            raise forbidden(f"Requires role: {', '.join(roles)}")
        return user

    return _dependency


require_admin = require_roles(ADMIN)
require_staff = require_roles(ADMIN, TEACHER)
require_student = require_roles(STUDENT)


def assert_student_scope(user: CurrentUser, prn: str) -> None:
    """Students may only read their own data."""
    if user.role == STUDENT and user.prn != prn:
        raise forbidden("Students can only access their own records")
