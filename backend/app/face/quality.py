"""Capture quality gates: face count, size, sharpness, lighting."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

from app.face.types import DetectedFace

ISSUE_MESSAGES: dict[str, str] = {
    "NO_FACE": "No face detected - face the camera in good light",
    "MULTIPLE_FACES": "More than one face in the frame - only one person should be visible",
    "FACE_TOO_SMALL": "Face is too small - move closer to the camera",
    "BLURRY": "Image is blurry - hold still and make sure the camera is focused",
    "TOO_DARK": "Too dark - add light in front of the face",
    "TOO_BRIGHT": "Over-exposed - reduce direct light / glare",
    "LOW_CONTRAST": "Low contrast - avoid washed-out lighting",
    "BACKLIT": "Strong back-light - do not stand in front of a window",
    "LOW_DETECTION_SCORE": "Face not clearly visible (partially covered or turned too far)",
    "NO_EMBEDDING": "Could not compute a face template",
}


@dataclass
class QualityReport:
    ok: bool
    issues: list[str] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "issues": self.issues,
            "messages": [ISSUE_MESSAGES.get(i, i) for i in self.issues],
            "metrics": {k: round(float(v), 3) for k, v in self.metrics.items()},
        }


def _face_region(img: np.ndarray, face: DetectedFace) -> np.ndarray:
    x1, y1, x2, y2 = face.bbox
    region = img[y1:y2, x1:x2]
    return region if region.size else img


def blur_score(gray: np.ndarray) -> float:
    """Variance of the Laplacian on a size-normalised crop (higher = sharper)."""
    norm = cv2.resize(gray, (160, 160), interpolation=cv2.INTER_AREA)
    return float(cv2.Laplacian(norm, cv2.CV_64F).var())


def assess_face(img: np.ndarray, face: DetectedFace, *, min_face_px: int, blur_threshold: float,
                brightness_min: float, brightness_max: float, min_det_score: float) -> QualityReport:
    issues: list[str] = []
    gray_full = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray_face = cv2.cvtColor(_face_region(img, face), cv2.COLOR_BGR2GRAY)

    brightness = float(gray_face.mean())
    contrast = float(gray_face.std())
    sharpness = blur_score(gray_face)
    background = float(gray_full.mean())

    if face.min_side < min_face_px:
        issues.append("FACE_TOO_SMALL")
    if sharpness < blur_threshold:
        issues.append("BLURRY")
    if brightness < brightness_min:
        issues.append("TOO_DARK")
    elif brightness > brightness_max:
        issues.append("TOO_BRIGHT")
    if contrast < 18:
        issues.append("LOW_CONTRAST")
    if background - brightness > 70:
        issues.append("BACKLIT")
    if face.det_score < min_det_score:
        issues.append("LOW_DETECTION_SCORE")
    if face.embedding is None:
        issues.append("NO_EMBEDDING")

    return QualityReport(
        ok=not issues,
        issues=issues,
        metrics={"brightness": brightness, "contrast": contrast, "sharpness": sharpness,
                 "face_px": float(face.min_side), "det_score": float(face.det_score)},
    )


def assess_single_capture(img: np.ndarray, faces: list[DetectedFace], **thresholds: float) -> QualityReport:
    """Exactly one face that passes every quality gate."""
    if not faces:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        report = QualityReport(ok=False, issues=["NO_FACE"],
                               metrics={"brightness": float(gray.mean()), "sharpness": blur_score(gray)})
        if report.metrics["brightness"] < thresholds.get("brightness_min", 50):
            report.issues.append("TOO_DARK")
        return report
    if len(faces) > 1:
        return QualityReport(ok=False, issues=["MULTIPLE_FACES"], metrics={"faces": float(len(faces))})
    return assess_face(img, faces[0], **thresholds)  # type: ignore[arg-type]
