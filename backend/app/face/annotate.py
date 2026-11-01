"""Draw recognition results on the group photo."""
from __future__ import annotations

import unicodedata
from typing import Any

import cv2
import numpy as np

# BGR colours per recognition status
COLORS: dict[str, tuple[int, int, int]] = {
    "MATCHED": (94, 197, 34),
    "LOW_CONFIDENCE": (11, 158, 245),
    "POSSIBLE": (0, 115, 249),
    "UNKNOWN": (68, 68, 239),
    "SPOOF_SUSPECTED": (247, 85, 168),
    "TOO_SMALL": (160, 160, 160),
}


def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def annotate(img: np.ndarray, faces: list[dict[str, Any]]) -> np.ndarray:
    out = img.copy()
    h, w = out.shape[:2]
    scale = max(0.45, min(1.2, w / 1400.0))
    thickness = max(2, int(round(w / 600)))
    for face in faces:
        x1, y1, x2, y2 = face["bbox"]
        color = COLORS.get(face.get("status", "UNKNOWN"), COLORS["UNKNOWN"])
        cv2.rectangle(out, (x1, y1), (x2, y2), color, thickness)
        name = face.get("name") or "Unknown"
        conf = face.get("confidence")
        label = f"#{face['face_index'] + 1} {_ascii(name)}" + (f" {conf:.2f}" if conf is not None else "")
        (tw, th), base = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)
        ty = y1 - 6 if y1 - th - 10 > 0 else y2 + th + 8
        lx = max(0, min(x1, w - tw - 9))  # keep the label inside the image
        cv2.rectangle(out, (lx, ty - th - 6), (lx + tw + 8, ty + base), color, -1)
        cv2.putText(out, label, (lx + 4, ty - 2), cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), 1, cv2.LINE_AA)
    return out
