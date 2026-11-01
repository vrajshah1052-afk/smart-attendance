"""Encryption at rest for face embeddings.

Fernet = AES-128-CBC + HMAC-SHA256 with a timestamp; tampering is detected.
MultiFernet allows key rotation: EMBEDDING_ENC_KEY="new_key,old_key" decrypts
with any key and always encrypts with the first one.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
from functools import lru_cache

import numpy as np
from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.config import get_settings


def _fernet(key: str) -> Fernet:
    """A Fernet key as is; any other secret (e.g. a host-generated value) via SHA-256."""
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, binascii.Error, UnicodeEncodeError):
        return Fernet(base64.urlsafe_b64encode(hashlib.sha256(key.encode("utf-8")).digest()))


class EmbeddingCipher:
    def __init__(self, keys: str) -> None:
        key_list = [k.strip() for k in keys.split(",") if k.strip()]
        if not key_list:
            raise ValueError("EMBEDDING_ENC_KEY is empty")
        self._fernet = MultiFernet([_fernet(k) for k in key_list])

    def encrypt(self, vector: np.ndarray) -> bytes:
        data = np.asarray(vector, dtype="<f4").tobytes()
        return self._fernet.encrypt(data)

    def decrypt(self, token: bytes) -> np.ndarray:
        try:
            raw = self._fernet.decrypt(bytes(token))
        except InvalidToken as exc:
            raise ValueError("Embedding could not be decrypted (wrong key or tampered data)") from exc
        return np.frombuffer(raw, dtype="<f4").copy()

    def rotate(self, token: bytes) -> bytes:
        """Re-encrypt with the primary key (used by key-rotation jobs)."""
        return self._fernet.rotate(bytes(token))


@lru_cache
def get_cipher() -> EmbeddingCipher:
    return EmbeddingCipher(get_settings().embedding_enc_key)
