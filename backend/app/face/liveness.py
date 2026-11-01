"""Liveness / anti-spoofing.

Active challenge (primary defence) on a burst of frames:
  * TURN_HEAD : yaw must sweep >= LIVENESS_MIN_YAW_DELTA degrees. A printed
                photo or a still image on a phone stays frontal.
  * BLINK     : eye-aspect-ratio must drop (eyes close) and recover.
Consistency checks:
  * the same identity in every frame (no face swapping mid-sequence)
  * natural micro-motion between frames (a replayed identical frame or a
    photo on a tripod is "too static")
Passive cues (advisory, configurable):
  * moire / periodic spectral peaks typical of re-captured screens
  * specular glare typical of glossy prints / screens
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

from app.face.types import DetectedFace

CHALLENGES = ("TURN_HEAD", "BLINK")

CHALLENGE_INSTRUCTIONS = {
    "TURN_HEAD": "Slowly turn your head to the LEFT and then to the RIGHT",
    "BLINK": "Look at the camera and BLINK slowly two times",
}

REASON_MESSAGES = {
    "INSUFFICIENT_FRAMES": "Not enough frames with exactly one clear face",
    "IDENTITY_CHANGED": "A different face appeared during the check",
    "STATIC_IMAGE": "No natural movement detected (photo or frozen video?)",
    "NO_HEAD_TURN": "Head turn not detected",
    "NO_BLINK": "Blink not detected",
    "POSE_UNAVAILABLE": "Head pose could not be estimated",
    "EYES_UNAVAILABLE": "Eyes could not be tracked",
    "SCREEN_ARTIFACTS": "Screen re-capture pattern (moire) detected",
    "SCREEN_GLARE": "Strong specular glare typical of a phone screen or glossy print",
    "UNKNOWN_CHALLENGE": "Unknown liveness challenge",
}


@dataclass
class LivenessResult:
    passed: bool
    challenge: str
    score: float
    reasons: list[str] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "challenge": self.challenge,
            "score": round(self.score, 3),
            "reasons": self.reasons,
            "messages": [REASON_MESSAGES.get(r, r) for r in self.reasons],
            "metrics": {k: round(float(v), 3) for k, v in self.metrics.items()},
        }


def _face_gray(img: np.ndarray, bbox: tuple[int, int, int, int], size: int, pad: float = 0.1) -> np.ndarray:
    h, w = img.shape[:2]
    x1, y1, x2, y2 = bbox
    px, py = int((x2 - x1) * pad), int((y2 - y1) * pad)
    crop = img[max(0, y1 - py):min(h, y2 + py), max(0, x1 - px):min(w, x2 + px)]
    if crop.size == 0:
        crop = img
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    return cv2.resize(gray, (size, size), interpolation=cv2.INTER_AREA).astype(np.float32)


def screen_artifact_scores(img: np.ndarray, bbox: tuple[int, int, int, int]) -> dict[str, float]:
    """Passive cues. moire = strongest isolated spectral peak above its local level (ln units)."""
    gray = _face_gray(img, bbox, 256)
    window = np.outer(np.hanning(256), np.hanning(256)).astype(np.float32)
    spectrum = np.log1p(np.abs(np.fft.fftshift(np.fft.fft2((gray - gray.mean()) * window))))
    local = cv2.GaussianBlur(spectrum, (0, 0), 3)
    residual = spectrum - local
    yy, xx = np.ogrid[:256, :256]
    radius = np.sqrt((yy - 128) ** 2 + (xx - 128) ** 2)
    band = (radius > 16) & (radius < 120)
    band &= (np.abs(yy - 128) > 2) & (np.abs(xx - 128) > 2)  # ignore window/edge cross
    moire = float(np.percentile(residual[band], 99.95))

    x1, y1, x2, y2 = bbox
    face = img[y1:y2, x1:x2]
    glare = 0.0
    if face.size:
        hsv = cv2.cvtColor(face, cv2.COLOR_BGR2HSV)
        glare = float(np.mean((hsv[..., 2] > 245) & (hsv[..., 1] < 40)))
    return {"moire": moire, "glare": glare}


def _cos(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / ((np.linalg.norm(a) * np.linalg.norm(b)) or 1.0))


def evaluate_liveness(
    frames: list[np.ndarray],
    faces_per_frame: list[list[DetectedFace]],
    challenge: str,
    *,
    min_frames: int,
    min_yaw_delta: float,
    ear_closed: float,
    ear_drop_ratio: float,
    static_diff: float,
    identity_threshold: float,
    moire_threshold: float,
    glare_threshold: float,
) -> LivenessResult:
    reasons: list[str] = []
    metrics: dict[str, float] = {}
    if challenge not in CHALLENGES:
        return LivenessResult(False, challenge, 0.0, ["UNKNOWN_CHALLENGE"])

    single = [(img, fs[0]) for img, fs in zip(frames, faces_per_frame) if len(fs) == 1]
    metrics["frames_used"] = float(len(single))
    if len(single) < min_frames:
        return LivenessResult(False, challenge, 0.0, ["INSUFFICIENT_FRAMES"], metrics)

    # 1. same person in every frame
    embeddings = [f.embedding for _, f in single if f.embedding is not None]
    if len(embeddings) >= 2:
        centroid = np.mean(np.stack(embeddings), axis=0)
        min_sim = min(_cos(e, centroid) for e in embeddings)
        metrics["identity_min_sim"] = min_sim
        if min_sim < identity_threshold:
            reasons.append("IDENTITY_CHANGED")

    # 2. natural motion between frames
    crops = [_face_gray(img, f.bbox, 64) for img, f in single]
    diffs = [float(np.mean(np.abs(crops[i] - crops[i - 1]))) for i in range(1, len(crops))]
    motion = float(np.median(diffs)) if diffs else 0.0
    metrics["motion"] = motion
    if motion < static_diff:
        reasons.append("STATIC_IMAGE")

    # 3. the active challenge
    challenge_score = 0.0
    if challenge == "TURN_HEAD":
        yaws = [f.yaw for _, f in single if f.yaw is not None]
        if len(yaws) < 2:
            reasons.append("POSE_UNAVAILABLE")
        else:
            yaw_range = float(max(yaws) - min(yaws))
            metrics["yaw_range"] = yaw_range
            challenge_score = min(1.0, yaw_range / (2 * min_yaw_delta))
            if yaw_range < min_yaw_delta:
                reasons.append("NO_HEAD_TURN")
    else:  # BLINK
        ears = [f.eye_ratio for _, f in single if f.eye_ratio is not None]
        if len(ears) < 2:
            reasons.append("EYES_UNAVAILABLE")
        else:
            ear_min, ear_max = float(min(ears)), float(max(ears))
            metrics.update({"ear_min": ear_min, "ear_max": ear_max})
            ratio = ear_min / ear_max if ear_max > 0 else 1.0
            challenge_score = max(0.0, min(1.0, (1.0 - ratio) / (1.0 - ear_drop_ratio + 1e-6)))
            if not (ear_min < ear_closed and ratio < ear_drop_ratio):
                reasons.append("NO_BLINK")

    # 4. passive screen / print cues (strongest frame counts)
    scores = [screen_artifact_scores(img, f.bbox) for img, f in single]
    moire = max(s["moire"] for s in scores)
    glare = max(s["glare"] for s in scores)
    metrics.update({"moire": moire, "glare": glare})
    if moire > moire_threshold:
        reasons.append("SCREEN_ARTIFACTS")
    if glare > glare_threshold:
        reasons.append("SCREEN_GLARE")

    passive_penalty = min(1.0, max(0.0, moire / (moire_threshold * 1.5))) * 0.3
    score = max(0.0, min(1.0, 0.7 * challenge_score + 0.3 * min(1.0, motion / (static_diff * 3)) - passive_penalty))
    return LivenessResult(not reasons, challenge, score, reasons, metrics)
