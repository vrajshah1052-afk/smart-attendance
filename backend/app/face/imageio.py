"""Image decoding / encoding helpers with defensive validation."""
from __future__ import annotations

import base64
import binascii

import cv2
import numpy as np
from fastapi import UploadFile

from app.core.errors import AppError

MAX_SIDE = 1920
MIN_SIDE = 64


def read_upload(file: UploadFile, max_bytes: int) -> bytes:
    data = file.file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise AppError(413, "FILE_TOO_LARGE", f"'{file.filename}' exceeds {max_bytes // (1024 * 1024)} MB")
    if not data:
        raise AppError(400, "EMPTY_FILE", f"'{file.filename}' is empty")
    return data


def decode_image(data: bytes, max_side: int = MAX_SIDE) -> np.ndarray:
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise AppError(400, "INVALID_IMAGE", "File is not a readable JPEG/PNG/WebP image")
    h, w = img.shape[:2]
    if min(h, w) < MIN_SIDE:
        raise AppError(400, "IMAGE_TOO_SMALL", f"Image must be at least {MIN_SIDE}px on each side")
    if max(h, w) > max_side:
        scale = max_side / float(max(h, w))
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    return img


def decode_data_url(value: str) -> bytes:
    payload = value.split(",", 1)[1] if value.startswith("data:") else value
    try:
        return base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise AppError(400, "INVALID_IMAGE", "Invalid base64 image payload") from exc


def encode_jpeg(img: np.ndarray, quality: int = 85) -> bytes:
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise AppError(500, "ENCODE_FAILED", "Could not encode image")
    return buf.tobytes()


def to_data_url(jpeg: bytes, mime: str = "image/jpeg") -> str:
    return f"data:{mime};base64,{base64.b64encode(jpeg).decode('ascii')}"


def crop_face(img: np.ndarray, bbox: tuple[int, int, int, int], pad: float = 0.25, size: int | None = 112) -> np.ndarray:
    h, w = img.shape[:2]
    x1, y1, x2, y2 = bbox
    pw, ph = int((x2 - x1) * pad), int((y2 - y1) * pad)
    x1, y1 = max(0, x1 - pw), max(0, y1 - ph)
    x2, y2 = min(w, x2 + pw), min(h, y2 + ph)
    crop = img[y1:y2, x1:x2]
    if crop.size == 0:
        crop = img
    if size:
        ch, cw = crop.shape[:2]
        scale = size / float(max(ch, cw))
        crop = cv2.resize(crop, (max(1, int(cw * scale)), max(1, int(ch * scale))), interpolation=cv2.INTER_AREA)
    return crop
