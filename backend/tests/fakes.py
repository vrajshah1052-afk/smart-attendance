"""Deterministic face engine + synthetic images for tests.

Images are random-noise PNGs (lossless, so the decoded pixels are identical);
each image is registered with the faces it "contains". This lets the tests
exercise the real pipeline (decode, quality gates, liveness, matching, sagas,
SQL procedures) without downloading a 280 MB model.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import threading

import cv2
import numpy as np

from app.face.types import DetectedFace, FaceEngine

DIM = 512


class FakeEngine(FaceEngine):
    name = "fake"
    model_id = "fake-512"
    dim = DIM
    default_threshold = 0.45
    default_duplicate_threshold = 0.60
    supports_pose = True

    def __init__(self) -> None:
        self._faces: dict[str, list[DetectedFace]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def key(img: np.ndarray) -> str:
        return hashlib.sha1(np.ascontiguousarray(img).tobytes()).hexdigest()

    def register(self, img: np.ndarray, faces: list[DetectedFace]) -> None:
        with self._lock:
            self._faces[self.key(img)] = faces

    def detect(self, image_bgr: np.ndarray, max_faces: int = 0) -> list[DetectedFace]:
        with self._lock:
            faces = copy.deepcopy(self._faces.get(self.key(image_bgr), []))
        return faces[:max_faces] if max_faces else faces


_identity_seq = iter(range(700_000, 10_000_000))


def unique_identity() -> np.ndarray:
    """A face identity never used before in this test run."""
    return identity(next(_identity_seq))


def identity(seed: int) -> np.ndarray:
    v = np.random.default_rng(seed).standard_normal(DIM).astype(np.float32)
    return v / np.linalg.norm(v)


def variant(base: np.ndarray, seed: int, sim: float = 0.9) -> np.ndarray:
    """A vector whose cosine similarity to `base` is exactly `sim`."""
    noise = np.random.default_rng(seed).standard_normal(DIM).astype(np.float32)
    noise -= noise.dot(base) * base
    noise /= np.linalg.norm(noise)
    v = sim * base + np.sqrt(1 - sim ** 2) * noise
    return (v / np.linalg.norm(v)).astype(np.float32)


def noise_image(seed: int, h: int = 480, w: int = 640) -> np.ndarray:
    return np.random.default_rng(seed).integers(60, 200, size=(h, w, 3), dtype=np.uint8)


def png(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()


def face(embedding: np.ndarray | None, bbox: tuple[int, int, int, int] = (220, 100, 420, 340), *,
         yaw: float = 0.0, ear: float = 0.30, det: float = 0.95) -> DetectedFace:
    return DetectedFace(bbox=bbox, det_score=det, embedding=embedding, yaw=yaw, pitch=0.0, roll=0.0,
                        eye_ratio=ear)


class PhotoFactory:
    """Creates registered synthetic photos."""

    def __init__(self, engine: FakeEngine) -> None:
        self.engine = engine
        self._seed = 10_000

    def next_seed(self) -> int:
        self._seed += 1
        return self._seed

    def photo(self, faces: list[DetectedFace], seed: int | None = None) -> bytes:
        img = noise_image(seed if seed is not None else self.next_seed())
        self.engine.register(img, faces)
        return png(img)

    def enrolment_set(self, base: np.ndarray, n: int = 5, sim: float = 0.9) -> list[bytes]:
        yaws = np.linspace(-20, 20, n)
        return [self.photo([face(variant(base, self.next_seed(), sim), yaw=float(y))]) for y in yaws]

    def liveness_frames(self, base: np.ndarray, challenge: str, n: int = 6, static: bool = False) -> list[bytes]:
        if static:
            one = self.photo([face(variant(base, self.next_seed(), 0.9), yaw=0.0, ear=0.3)])
            return [one] * n
        frames = []
        for i in range(n):
            yaw = float(np.linspace(-25, 25, n)[i]) if challenge == "TURN_HEAD" else 0.0
            ear = 0.12 if (challenge == "BLINK" and i in (2, 3)) else 0.31
            frames.append(self.photo([face(variant(base, self.next_seed(), 0.92), yaw=yaw, ear=ear)]))
        return frames


def data_url(png_bytes: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")
