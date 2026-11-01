"""Engine-independent face data structures."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np


@dataclass
class DetectedFace:
    bbox: tuple[int, int, int, int]          # x1, y1, x2, y2 in image pixels
    det_score: float
    embedding: np.ndarray | None = None      # L2-normalised float32
    yaw: float | None = None                 # degrees, head pose
    pitch: float | None = None
    roll: float | None = None
    landmarks68: np.ndarray | None = None    # (68, 2) iBUG layout when available
    eye_ratio: float | None = None           # eye aspect ratio (blink detection)

    @property
    def width(self) -> int:
        return max(0, self.bbox[2] - self.bbox[0])

    @property
    def height(self) -> int:
        return max(0, self.bbox[3] - self.bbox[1])

    @property
    def min_side(self) -> int:
        return min(self.width, self.height)

    @property
    def area(self) -> int:
        return self.width * self.height

    def bbox_list(self) -> list[int]:
        return [int(v) for v in self.bbox]


def pose_label(yaw: float | None, pitch: float | None = None) -> str | None:
    """Human readable pose bucket (camera point of view)."""
    if yaw is None:
        return None
    if yaw <= -12:
        return "left"
    if yaw >= 12:
        return "right"
    if pitch is not None and pitch >= 12:
        return "up"
    if pitch is not None and pitch <= -12:
        return "down"
    return "front"


class FaceEngine(ABC):
    """Detector + embedder. Implementations must be thread-safe."""

    name: str = "abstract"
    model_id: str = "abstract"
    dim: int = 512
    default_threshold: float = 0.45
    default_duplicate_threshold: float = 0.60
    supports_pose: bool = False

    @abstractmethod
    def detect(self, image_bgr: np.ndarray, max_faces: int = 0) -> list[DetectedFace]:
        """Detect faces (largest first) and compute their embeddings."""

    def describe(self) -> dict[str, object]:
        return {
            "name": self.name,
            "model_id": self.model_id,
            "dim": self.dim,
            "default_threshold": self.default_threshold,
            "supports_pose": self.supports_pose,
        }


def l2_normalize(vec: np.ndarray) -> np.ndarray:
    v = np.asarray(vec, dtype=np.float32).ravel()
    norm = float(np.linalg.norm(v))
    return v / norm if norm > 0 else v


def eye_aspect_ratio(lm68: np.ndarray | None) -> float | None:
    """EAR (Soukupova & Cech 2016) averaged over both eyes; ~0.3 open, <0.2 closed."""
    if lm68 is None or len(lm68) < 48:
        return None

    def _ear(p: np.ndarray) -> float:
        a = np.linalg.norm(p[1] - p[5])
        b = np.linalg.norm(p[2] - p[4])
        c = np.linalg.norm(p[0] - p[3])
        return float((a + b) / (2.0 * c)) if c > 0 else 0.0

    pts = np.asarray(lm68, dtype=np.float32)[:, :2]
    return (_ear(pts[36:42]) + _ear(pts[42:48])) / 2.0
