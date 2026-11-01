"""Face engines.

1. InsightFace buffalo_l (RetinaFace det_10g + ArcFace w600k_r50, 512-d) - primary
2. Same buffalo_l ONNX models run directly on onnxruntime (no compiled
   insightface package needed, e.g. on Windows without a C++ toolchain)
3. face_recognition (dlib ResNet, 128-d)                                    - fallback
4. OpenCV Haar + LBP histogram (512-d)                                      - demo-only fallback
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

import cv2
import numpy as np

from app.face.types import DetectedFace, FaceEngine, eye_aspect_ratio, l2_normalize

logger = logging.getLogger(__name__)


def _clamp_bbox(bbox: np.ndarray, shape: tuple[int, ...]) -> tuple[int, int, int, int]:
    h, w = shape[:2]
    x1, y1, x2, y2 = (int(round(float(v))) for v in bbox[:4])
    return max(0, x1), max(0, y1), min(w, x2), min(h, y2)


# --------------------------------------------------------------------------- InsightFace
class InsightFaceEngine(FaceEngine):
    name = "insightface"
    dim = 512
    default_threshold = 0.45
    default_duplicate_threshold = 0.60
    supports_pose = True

    def __init__(self, model_name: str = "buffalo_l", root: str = "/models", det_size: int = 640) -> None:
        from insightface.app import FaceAnalysis  # heavy import, lazy

        self.model_id = f"insightface-{model_name}"
        self._app = FaceAnalysis(
            name=model_name,
            root=root,
            providers=["CPUExecutionProvider"],
            allowed_modules=["detection", "recognition", "landmark_3d_68"],
        )
        self._app.prepare(ctx_id=-1, det_size=(det_size, det_size))
        self._lock = threading.Lock()
        logger.info("InsightFace %s loaded (det_size=%d)", model_name, det_size)

    def detect(self, image_bgr: np.ndarray, max_faces: int = 0) -> list[DetectedFace]:
        with self._lock:
            faces = self._app.get(image_bgr, max_num=max_faces)
        results: list[DetectedFace] = []
        for f in faces:
            lm = getattr(f, "landmark_3d_68", None)
            lm2 = np.asarray(lm)[:, :2] if lm is not None else None
            pose = getattr(f, "pose", None)
            pitch, yaw, roll = (float(pose[0]), float(pose[1]), float(pose[2])) if pose is not None else (None, None, None)
            emb = getattr(f, "normed_embedding", None)
            results.append(DetectedFace(
                bbox=_clamp_bbox(f.bbox, image_bgr.shape),
                det_score=float(f.det_score),
                embedding=l2_normalize(emb) if emb is not None else None,
                yaw=yaw, pitch=pitch, roll=roll,
                landmarks68=lm2,
                eye_ratio=eye_aspect_ratio(lm2),
            ))
        results.sort(key=lambda d: d.area, reverse=True)
        return results


# ------------------------------------------------------------------- ArcFace on onnxruntime
# 5-point template ArcFace was trained on (insightface.utils.face_align.arcface_dst)
_ARCFACE_DST = np.array([[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366],
                         [41.5493, 92.3655], [70.7299, 92.2041]], dtype=np.float32)


def _umeyama(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """Least-squares similarity transform src -> dst (2x3), as skimage SimilarityTransform."""
    src_mean, dst_mean = src.mean(axis=0), dst.mean(axis=0)
    src_d, dst_d = src - src_mean, dst - dst_mean
    a = dst_d.T @ src_d / len(src)
    d = np.ones(2)
    if np.linalg.det(a) < 0:
        d[1] = -1
    u, s, vt = np.linalg.svd(a)
    rot = u @ np.diag(d) @ vt
    scale = (s @ d) / src_d.var(axis=0).sum()
    m = np.zeros((2, 3), dtype=np.float32)
    m[:, :2] = scale * rot
    m[:, 2] = dst_mean - scale * rot @ src_mean
    return m


def _nms(dets: np.ndarray, thresh: float) -> list[int]:
    x1, y1, x2, y2, scores = dets.T
    areas = (x2 - x1 + 1) * (y2 - y1 + 1)
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size > 0:
        i = order[0]
        keep.append(int(i))
        xx1, yy1 = np.maximum(x1[i], x1[order[1:]]), np.maximum(y1[i], y1[order[1:]])
        xx2, yy2 = np.minimum(x2[i], x2[order[1:]]), np.minimum(y2[i], y2[order[1:]])
        inter = np.maximum(0.0, xx2 - xx1 + 1) * np.maximum(0.0, yy2 - yy1 + 1)
        order = order[np.where(inter / (areas[i] + areas[order[1:]] - inter) <= thresh)[0] + 1]
    return keep


class ArcFaceOnnxEngine(FaceEngine):
    """buffalo_l pipeline (SCRFD -> 5-point alignment -> ArcFace, 1k3d68 landmarks) on onnxruntime.

    Mirrors insightface.app.FaceAnalysis without its compiled extension. Head pose
    comes from the depth of the 3D landmarks instead of insightface's mean-shape fit.
    """

    name = "arcface_onnx"
    dim = 512
    default_threshold = 0.45
    default_duplicate_threshold = 0.60
    supports_pose = True
    _strides = (8, 16, 32)

    def __init__(self, model_name: str = "buffalo_l", root: str = "/models", det_size: int = 640,
                 threads: int = 0, low_memory: bool = False) -> None:
        import onnxruntime as ort  # heavy import, lazy

        folder = Path(root) / "models" / model_name

        def find(*patterns: str) -> str:
            for pattern in patterns:
                hits = sorted(folder.glob(pattern))
                if hits:
                    return str(hits[0])
            raise RuntimeError(f"{patterns[0]} not found in {folder} (download {model_name}.zip and unzip it there)")

        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        if threads:
            opts.intra_op_num_threads = opts.inter_op_num_threads = threads
        if low_memory:  # small containers: no arena / pre-planned buffers, no weight-copying layout passes
            opts.enable_cpu_mem_arena = False
            opts.enable_mem_pattern = False
            opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC

        def session(path: str) -> "ort.InferenceSession":
            return ort.InferenceSession(path, sess_options=opts, providers=["CPUExecutionProvider"])

        self._det = session(find("det_*.onnx", "scrfd*.onnx"))
        self._rec = session(find("w600k_*.onnx", "glintr100.onnx"))
        self._lmk = session(find("1k3d68.onnx"))
        self._det_input = self._det.get_inputs()[0].name
        self._det_size = det_size
        self.model_id = f"arcface-onnx-{model_name}"
        self._lock = threading.Lock()
        logger.info("ArcFace ONNX %s loaded from %s (det_size=%d)", model_name, folder, det_size)

    # -- SCRFD detection (insightface.model_zoo.scrfd) ------------------------------
    def _detect_boxes(self, img: np.ndarray, thresh: float = 0.5) -> tuple[np.ndarray, np.ndarray]:
        size = self._det_size
        ratio = img.shape[0] / img.shape[1]
        new_h, new_w = (size, int(size / ratio)) if ratio > 1 else (int(size * ratio), size)
        scale = new_h / img.shape[0]
        canvas = np.zeros((size, size, 3), dtype=np.uint8)
        canvas[:new_h, :new_w] = cv2.resize(img, (new_w, new_h))
        blob = cv2.dnn.blobFromImage(canvas, 1.0 / 128, (size, size), (127.5, 127.5, 127.5), swapRB=True)
        outs = self._det.run(None, {self._det_input: blob})
        if outs[0].ndim == 3:
            outs = [o[0] for o in outs]
        fmc = len(self._strides)
        scores_l, boxes_l, kps_l = [], [], []
        for i, stride in enumerate(self._strides):
            scores = outs[i].ravel()
            dist, kdist = outs[i + fmc] * stride, outs[i + 2 * fmc] * stride
            h = w = size // stride
            centres = (np.stack(np.mgrid[:h, :w][::-1], axis=-1).astype(np.float32) * stride).reshape(-1, 2)
            centres = np.repeat(centres, len(scores) // len(centres), axis=0)
            pos = np.where(scores >= thresh)[0]
            c = centres[pos]
            boxes = np.hstack([c - dist[pos, :2], c + dist[pos, 2:4]])
            kps = np.stack([c + kdist[pos, k:k + 2] for k in range(0, 10, 2)], axis=1)
            scores_l.append(scores[pos])
            boxes_l.append(boxes)
            kps_l.append(kps)
        scores = np.concatenate(scores_l)
        boxes = np.vstack(boxes_l) / scale
        kps = np.concatenate(kps_l) / scale
        dets = np.hstack([boxes, scores[:, None]]).astype(np.float32)
        keep = _nms(dets, 0.4)
        return dets[keep], kps[keep]

    # -- 68 3D landmarks (insightface.model_zoo.landmark, 1k3d68) ---------------------
    def _landmarks(self, img: np.ndarray, bbox: np.ndarray) -> np.ndarray:
        size = 192
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        s = size / (max(w, h) * 1.5)
        cx, cy = (bbox[0] + bbox[2]) / 2 * s, (bbox[1] + bbox[3]) / 2 * s
        m = np.array([[s, 0, size / 2 - cx], [0, s, size / 2 - cy]], dtype=np.float32)
        crop = cv2.warpAffine(img, m, (size, size), borderValue=0.0)
        blob = cv2.dnn.blobFromImage(crop, 1.0, (size, size), (0.0, 0.0, 0.0), swapRB=True)
        pred = self._lmk.run(None, {self._lmk.get_inputs()[0].name: blob})[0][0].reshape(-1, 3)[-68:].copy()
        pred[:, :2] = (pred[:, :2] + 1) * (size // 2)
        pred[:, 2] *= size // 2
        inv = cv2.invertAffineTransform(m)
        pred[:, :2] = pred[:, :2] @ inv[:, :2].T + inv[:, 2]
        pred[:, 2] /= s
        return pred

    @staticmethod
    def _pose(lm3d: np.ndarray) -> tuple[float, float, float]:
        """(pitch, yaw, roll) in degrees from the outer eye corners and nose-bridge-to-chin line."""
        eye = lm3d[45] - lm3d[36]
        vert = lm3d[8] - lm3d[27]
        yaw = float(np.degrees(np.arctan2(eye[2], eye[0])))
        # the nasion-chin line of a face looking straight at the camera leans ~8 deg (measured)
        pitch = float(np.degrees(np.arctan2(vert[2], vert[1]))) - 8.0
        roll = float(np.degrees(np.arctan2(eye[1], eye[0])))
        return pitch, yaw, roll

    # -- ArcFace embedding (insightface.model_zoo.arcface_onnx) ------------------------
    def _embed(self, img: np.ndarray, kps: np.ndarray) -> np.ndarray:
        aligned = cv2.warpAffine(img, _umeyama(kps, _ARCFACE_DST), (112, 112), borderValue=0.0)
        blob = cv2.dnn.blobFromImage(aligned, 1.0 / 127.5, (112, 112), (127.5, 127.5, 127.5), swapRB=True)
        return self._rec.run(None, {self._rec.get_inputs()[0].name: blob})[0].ravel()

    def detect(self, image_bgr: np.ndarray, max_faces: int = 0) -> list[DetectedFace]:
        with self._lock:
            dets, kpss = self._detect_boxes(image_bgr)
            order = np.argsort(-(dets[:, 2] - dets[:, 0]) * (dets[:, 3] - dets[:, 1]))
            if max_faces:
                order = order[:max_faces]
            results: list[DetectedFace] = []
            for i in order:
                lm3d = self._landmarks(image_bgr, dets[i, :4])
                pitch, yaw, roll = self._pose(lm3d)
                lm2 = lm3d[:, :2]
                results.append(DetectedFace(
                    bbox=_clamp_bbox(dets[i, :4], image_bgr.shape),
                    det_score=float(dets[i, 4]),
                    embedding=l2_normalize(self._embed(image_bgr, kpss[i])),
                    yaw=yaw, pitch=pitch, roll=roll,
                    landmarks68=lm2,
                    eye_ratio=eye_aspect_ratio(lm2),
                ))
        return results


# ---------------------------------------------------------------------- face_recognition
class FaceRecognitionEngine(FaceEngine):
    name = "face_recognition"
    model_id = "dlib-resnet-128"
    dim = 128
    # dlib's 0.6 euclidean distance on ~unit vectors ~= cosine 0.82
    default_threshold = 0.82
    default_duplicate_threshold = 0.90
    supports_pose = True

    def __init__(self) -> None:
        import face_recognition  # noqa: F401  (raises ImportError when dlib is missing)

        self._fr = face_recognition
        self._lock = threading.Lock()
        logger.info("face_recognition (dlib) engine loaded")

    def detect(self, image_bgr: np.ndarray, max_faces: int = 0) -> list[DetectedFace]:
        rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        with self._lock:
            locations = self._fr.face_locations(rgb, model="hog")
            encodings = self._fr.face_encodings(rgb, locations)
            landmarks = self._fr.face_landmarks(rgb, locations)
        results: list[DetectedFace] = []
        for (top, right, bottom, left), enc, lms in zip(locations, encodings, landmarks):
            yaw = None
            ear = None
            if lms:
                nose = np.mean(np.array(lms.get("nose_bridge", []), dtype=np.float32), axis=0)
                cx = (left + right) / 2.0
                yaw = float((nose[0] - cx) / max(1.0, (right - left)) * 120.0)
                if "left_eye" in lms and "right_eye" in lms:
                    pts = np.zeros((68, 2), dtype=np.float32)
                    pts[36:42] = np.array(lms["left_eye"], dtype=np.float32)
                    pts[42:48] = np.array(lms["right_eye"], dtype=np.float32)
                    ear = eye_aspect_ratio(pts)
            results.append(DetectedFace(
                bbox=_clamp_bbox(np.array([left, top, right, bottom]), image_bgr.shape),
                det_score=0.9, embedding=l2_normalize(enc), yaw=yaw, eye_ratio=ear,
            ))
        results.sort(key=lambda d: d.area, reverse=True)
        return results[:max_faces] if max_faces else results


# ------------------------------------------------------------------------ OpenCV LBP
def lbp_embedding(gray_face: np.ndarray) -> np.ndarray:
    """4x4 grid of 32-bin uniform-ish LBP histograms -> 512-d, Hellinger + centred."""
    g = cv2.equalizeHist(cv2.resize(gray_face, (98, 98))).astype(np.int16)
    c = g[1:-1, 1:-1]
    codes = np.zeros(c.shape, dtype=np.uint8)
    offsets = [(-1, -1), (-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1)]
    h, w = g.shape
    for bit, (dy, dx) in enumerate(offsets):
        neighbour = g[1 + dy:h - 1 + dy, 1 + dx:w - 1 + dx]
        codes |= ((neighbour >= c).astype(np.uint8) << np.uint8(bit))
    ch, cw = codes.shape[0] // 4, codes.shape[1] // 4
    feats = []
    for i in range(4):
        for j in range(4):
            cell = codes[i * ch:(i + 1) * ch, j * cw:(j + 1) * cw]
            feats.append(np.bincount((cell >> 3).ravel(), minlength=32).astype(np.float32))
    vec = np.sqrt(np.concatenate(feats))
    vec -= vec.mean()
    return l2_normalize(vec)


class OpenCVEngine(FaceEngine):
    name = "opencv"
    model_id = "opencv-haar-lbp-512"
    dim = 512
    default_threshold = 0.55
    default_duplicate_threshold = 0.85
    supports_pose = True

    def __init__(self) -> None:
        base = cv2.data.haarcascades
        self._face = cv2.CascadeClassifier(base + "haarcascade_frontalface_default.xml")
        self._eyes = cv2.CascadeClassifier(base + "haarcascade_eye.xml")
        if self._face.empty():
            raise RuntimeError("OpenCV Haar cascade not found")
        logger.warning("Using OpenCV LBP fallback engine (demo quality only)")

    def detect(self, image_bgr: np.ndarray, max_faces: int = 0) -> list[DetectedFace]:
        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
        boxes = self._face.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=6, minSize=(24, 24))
        results: list[DetectedFace] = []
        for (x, y, w, h) in boxes:
            crop = gray[y:y + h, x:x + w]
            eyes = self._eyes.detectMultiScale(crop[: h // 2 + h // 8], scaleFactor=1.1, minNeighbors=5,
                                               minSize=(max(8, w // 10), max(8, w // 10)))
            yaw = None
            if len(eyes) >= 2:
                centres = sorted([(ex + ew / 2.0) for (ex, _ey, ew, _eh) in eyes[:2]])
                mid = (centres[0] + centres[1]) / 2.0
                yaw = float((mid - w / 2.0) / w * 120.0)
            results.append(DetectedFace(
                bbox=(int(x), int(y), int(x + w), int(y + h)), det_score=0.9,
                embedding=lbp_embedding(crop), yaw=yaw,
                eye_ratio=0.30 if len(eyes) >= 2 else (0.22 if len(eyes) == 1 else 0.10),
            ))
        results.sort(key=lambda d: d.area, reverse=True)
        return results[:max_faces] if max_faces else results


# ------------------------------------------------------------------------ factory
def create_engine(kind: str, model_name: str, root: str, det_size: int, threads: int = 0,
                  low_memory: bool = False) -> FaceEngine:
    kind = (kind or "auto").lower()
    order = ["insightface", "arcface_onnx", "face_recognition", "opencv"] if kind == "auto" else [kind]
    errors: list[str] = []
    for candidate in order:
        try:
            if candidate == "insightface":
                return InsightFaceEngine(model_name=model_name, root=root, det_size=det_size)
            if candidate == "arcface_onnx":
                return ArcFaceOnnxEngine(model_name=model_name, root=root, det_size=det_size, threads=threads,
                                         low_memory=low_memory)
            if candidate == "face_recognition":
                return FaceRecognitionEngine()
            if candidate == "opencv":
                return OpenCVEngine()
            raise ValueError(f"Unknown FACE_ENGINE '{candidate}'")
        except Exception as exc:  # noqa: BLE001 - try the next engine
            logger.warning("Face engine '%s' unavailable: %s", candidate, exc)
            errors.append(f"{candidate}: {exc}")
    raise RuntimeError("No face engine could be loaded -> " + " | ".join(errors))
