"""Download InsightFace buffalo_l into INSIGHTFACE_ROOT (used at docker build time)."""
from __future__ import annotations

import os
import sys


def main() -> int:
    root = os.environ.get("INSIGHTFACE_ROOT", "/models")
    name = os.environ.get("INSIGHTFACE_MODEL", "buffalo_l")
    from insightface.app import FaceAnalysis

    app = FaceAnalysis(name=name, root=root, providers=["CPUExecutionProvider"],
                       allowed_modules=["detection", "recognition", "landmark_3d_68"])
    app.prepare(ctx_id=-1, det_size=(640, 640))
    print(f"InsightFace model '{name}' ready in {root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
