"""Liveness challenge tokens (signed, short-lived, single use) and rotating QR codes."""
from __future__ import annotations

import base64
import hashlib
import hmac
import io
import secrets
import time
from typing import Any

import qrcode
from pymongo.errors import DuplicateKeyError, PyMongoError

from app.config import get_settings
from app.core.errors import AppError
from app.core.security import create_signed_token, decode_token
from app.core.utils import utcnow
from app.db.mongo import C, col
from app.face.liveness import CHALLENGE_INSTRUCTIONS, CHALLENGES

_used_nonces_fallback: dict[str, float] = {}


# ------------------------------------------------------------- liveness
def issue_challenge(user_id: int) -> dict[str, Any]:
    s = get_settings()
    challenge = secrets.choice(CHALLENGES)
    nonce = secrets.token_urlsafe(12)
    token = create_signed_token({"ch": challenge, "nonce": nonce, "uid": user_id}, s.liveness_challenge_ttl,
                                "liveness")
    return {
        "challenge": challenge,
        "instructions": CHALLENGE_INSTRUCTIONS[challenge],
        "token": token,
        "expires_in": s.liveness_challenge_ttl,
        "frames": 12,
        "interval_ms": 200,
    }


def consume_challenge(token: str, user_id: int) -> str:
    """Verify signature/expiry/owner and burn the nonce (replay protection)."""
    try:
        payload = decode_token(token, expected_type="liveness")
    except AppError as exc:
        raise AppError(400, "CHALLENGE_INVALID", "Liveness challenge is invalid or expired - start again") from exc
    if payload.get("uid") != user_id:
        raise AppError(400, "CHALLENGE_INVALID", "Challenge was issued to another user")
    nonce = str(payload.get("nonce"))
    try:
        col(C.LIVENESS_NONCES).insert_one({"nonce": nonce, "created_at": utcnow()})
    except DuplicateKeyError as exc:
        raise AppError(400, "CHALLENGE_REUSED", "This liveness challenge was already used") from exc
    except PyMongoError:
        now = time.time()
        for key, ts in list(_used_nonces_fallback.items()):
            if now - ts > 600:
                _used_nonces_fallback.pop(key, None)
        if nonce in _used_nonces_fallback:
            raise AppError(400, "CHALLENGE_REUSED", "This liveness challenge was already used")
        _used_nonces_fallback[nonce] = now
    challenge = str(payload.get("ch"))
    if challenge not in CHALLENGES:
        raise AppError(400, "CHALLENGE_INVALID", "Unknown challenge")
    return challenge


# ------------------------------------------------------------- QR fallback
def _window(offset: int = 0) -> int:
    return int(time.time() // get_settings().qr_window_seconds) + offset


def qr_code_for(session_id: int, window: int | None = None) -> str:
    """TOTP-style 6 digit code = HMAC(secret, session:window)."""
    secret = get_settings().jwt_secret.encode("utf-8")
    msg = f"qr:{session_id}:{window if window is not None else _window()}".encode("utf-8")
    digest = hmac.new(secret, msg, hashlib.sha256).digest()
    number = int.from_bytes(digest[:4], "big") % 1_000_000
    return f"{number:06d}"


def verify_qr_code(session_id: int, code: str) -> bool:
    # accept the current and the previous window (clock skew / slow scan)
    return any(hmac.compare_digest(qr_code_for(session_id, _window(off)), code) for off in (0, -1))


def qr_png(url: str, box_size: int = 8) -> str:
    """QR image of `url` as a data: URL."""
    img = qrcode.make(url, box_size=box_size, border=2)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def qr_payload(session_id: int) -> dict[str, Any]:
    s = get_settings()
    code = qr_code_for(session_id)
    url = f"{s.public_url}/qr/{session_id}/{code}"
    remaining = s.qr_window_seconds - int(time.time()) % s.qr_window_seconds
    return {
        "session_id": session_id,
        "code": code,
        "url": url,
        "expires_in": remaining,
        "qr_png": qr_png(url),
    }
