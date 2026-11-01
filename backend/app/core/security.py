"""Password hashing (bcrypt) and JWT access tokens."""
from __future__ import annotations

import re
import secrets
import string
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.config import get_settings
from app.core.errors import AppError

_PASSWORD_RE = re.compile(r"^(?=.*[A-Za-z])(?=.*\d).{8,72}$")


def validate_password_strength(password: str) -> None:
    if len(password.encode("utf-8")) > 72 or not _PASSWORD_RE.match(password):
        raise AppError(422, "WEAK_PASSWORD",
                       "Password must be 8-72 characters and contain at least one letter and one digit")


def hash_password(password: str, rounds: int | None = None) -> str:
    cost = rounds or get_settings().bcrypt_rounds
    return bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt(rounds=cost)).decode("ascii")


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:72], password_hash.encode("ascii"))
    except ValueError:
        return False


# A real hash used to equalise timing when the user does not exist
_DUMMY_HASH = bcrypt.hashpw(b"timing-equaliser", bcrypt.gensalt(rounds=4)).decode("ascii")


def dummy_verify() -> None:
    bcrypt.checkpw(b"not-the-password", _DUMMY_HASH.encode("ascii"))


def generate_temp_password(length: int = 10) -> str:
    alphabet = string.ascii_letters + string.digits
    while True:
        candidate = "".join(secrets.choice(alphabet) for _ in range(length))
        if any(c.isdigit() for c in candidate) and any(c.isalpha() for c in candidate):
            return candidate


def create_access_token(subject: str, claims: dict[str, Any], expires_minutes: int | None = None) -> tuple[str, int]:
    settings = get_settings()
    minutes = expires_minutes or settings.jwt_expire_minutes
    now = datetime.now(timezone.utc)
    payload = {"sub": subject, "iat": now, "exp": now + timedelta(minutes=minutes), "typ": "access", **claims}
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, minutes * 60


def decode_token(token: str, expected_type: str = "access") -> dict[str, Any]:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise AppError(401, "TOKEN_EXPIRED", "Token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AppError(401, "TOKEN_INVALID", "Invalid token") from exc
    if payload.get("typ") != expected_type:
        raise AppError(401, "TOKEN_INVALID", "Wrong token type")
    return payload


def create_signed_token(claims: dict[str, Any], ttl_seconds: int, token_type: str) -> str:
    """Short-lived signed token for non-auth purposes (liveness challenges)."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {"iat": now, "exp": now + timedelta(seconds=ttl_seconds), "typ": token_type, **claims}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
