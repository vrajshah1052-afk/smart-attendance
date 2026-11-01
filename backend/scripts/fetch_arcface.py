"""Download an insightface model pack for the arcface_onnx engine (no insightface package needed).

    python -m scripts.fetch_arcface buffalo_s /models      -> /models/models/buffalo_s/*.onnx

Only the three models the engine loads are kept: detector (det_*), recogniser
(w600k_*) and the 68-point 3D landmarks (1k3d68). buffalo_s is ~5x lighter than
buffalo_l and fits a 512 MB container.

With the `onnx` package installed, models over 32 MB are re-saved with their weights
in a side file (external data). onnxruntime then maps the weights instead of copying
them while loading: the 137 MB landmark model peaks ~100 MB lower.
"""
from __future__ import annotations

import io
import sys
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

URL = "https://github.com/deepinsight/insightface/releases/download/v0.7/{name}.zip"
KEEP = ("det_", "w600k_", "1k3d68")


def fetch(name: str, root: str) -> list[str]:
    target = Path(root) / "models" / name
    target.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(URL.format(name=name), timeout=120) as res:
        data = res.read()
    kept = []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for info in archive.infolist():
            file = PurePosixPath(info.filename).name  # some packs nest the files in a folder
            if file.endswith(".onnx") and file.startswith(KEEP):
                (target / file).write_bytes(archive.read(info))
                kept.append(file)
    if len(kept) != len(KEEP):
        raise SystemExit(f"{name}.zip is missing models: kept only {kept}")
    for file in kept:
        if (target / file).stat().st_size > 32 * 2**20:
            externalise(target / file)
    return sorted(kept)


def externalise(path: Path) -> None:
    try:
        import onnx
        from onnx import numpy_helper
    except ImportError:
        print("onnx not installed: keeping", path.name, "as one file")
        return
    model = onnx.load(str(path))
    for tensor in model.graph.initializer:  # insightface stores weights as float_data; external data needs raw_data
        if not tensor.HasField("raw_data"):
            tensor.CopyFrom(numpy_helper.from_array(numpy_helper.to_array(tensor), tensor.name))
    onnx.save_model(model, str(path), save_as_external_data=True, all_tensors_to_one_file=True,
                    location=path.name + ".data", size_threshold=1024)


if __name__ == "__main__":
    args = sys.argv[1:]
    model = args[0] if args else "buffalo_s"
    models_root = args[1] if len(args) > 1 else "/models"
    print(model, "->", fetch(model, models_root))
