"""Shared face-processing pipeline: enrolment photos, matching, duplicates."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.config import get_settings
from app.face.imageio import crop_face, decode_image, encode_jpeg, to_data_url
from app.face.liveness import screen_artifact_scores
from app.face.matcher import Candidate, assign_unique, classify
from app.face.quality import assess_single_capture
from app.face.types import DetectedFace, l2_normalize, pose_label
from app.services import face_service

logger = logging.getLogger(__name__)


@dataclass
class EnrolmentPhoto:
    index: int
    embedding: np.ndarray | None
    yaw: float | None
    pitch: float | None
    pose: str | None
    quality: dict[str, Any]
    accepted: bool
    issues: list[str] = field(default_factory=list)

    def public(self) -> dict[str, Any]:
        return {"index": self.index, "accepted": self.accepted, "issues": self.issues,
                "messages": self.quality.get("messages", []), "pose": self.pose,
                "yaw": round(self.yaw, 1) if self.yaw is not None else None,
                "metrics": self.quality.get("metrics", {})}


def analyse_enrolment_photo(index: int, data: bytes) -> EnrolmentPhoto:
    """Decode -> detect -> single-face quality gate -> passive screen check."""
    img = decode_image(data)
    faces = face_service.detect(img, max_faces=0)
    report = assess_single_capture(img, faces, **face_service.quality_thresholds())
    issues = list(report.issues)
    face = faces[0] if len(faces) == 1 else None
    if face is not None:
        passive = screen_artifact_scores(img, face.bbox)
        report.metrics.update(passive)
        s = get_settings()
        if passive["moire"] > s.moire_threshold:
            issues.append("SCREEN_ARTIFACTS")
        if passive["glare"] > s.glare_threshold:
            issues.append("SCREEN_GLARE")
    quality = report.to_dict()
    quality["issues"] = issues
    return EnrolmentPhoto(
        index=index,
        embedding=face.embedding if face is not None else None,
        yaw=face.yaw if face is not None else None,
        pitch=face.pitch if face is not None else None,
        pose=pose_label(face.yaw, face.pitch) if face is not None else None,
        quality=quality,
        accepted=not issues and face is not None and face.embedding is not None,
        issues=issues,
    )


def enforce_same_person(photos: list[EnrolmentPhoto]) -> None:
    """All accepted photos must show the same person (reject the outliers)."""
    accepted = [p for p in photos if p.accepted]
    if len(accepted) < 2:
        return
    centroid = l2_normalize(np.mean(np.stack([p.embedding for p in accepted]), axis=0))
    threshold = face_service.match_threshold()
    for p in accepted:
        if float(np.dot(p.embedding, centroid)) < threshold:
            p.accepted = False
            p.issues.append("DIFFERENT_PERSON")
            p.quality.setdefault("messages", []).append("This photo does not look like the same person")


def pose_range(photos: list[EnrolmentPhoto]) -> float | None:
    yaws = [p.yaw for p in photos if p.accepted and p.yaw is not None]
    return float(max(yaws) - min(yaws)) if len(yaws) >= 2 else None


def find_duplicate(embeddings: list[np.ndarray], exclude_prn: str | None = None) -> Candidate | None:
    """Same face already enrolled under a different PRN?"""
    index = face_service.refresh_index()
    if index.size == 0 or not embeddings:
        return None
    threshold = face_service.duplicate_threshold()
    best: Candidate | None = None
    for emb in embeddings:
        for cand in index.top_k(emb, k=2, exclude=exclude_prn):
            if cand.prn != exclude_prn and cand.score >= threshold and (best is None or cand.score > best.score):
                best = cand
    return best


# ------------------------------------------------------------------ matching
@dataclass
class FaceResult:
    face_index: int
    bbox: list[int]
    det_score: float
    prn: str | None
    confidence: float | None
    status: str
    suggestions: list[dict[str, Any]]
    spoof: dict[str, float] | None
    embedding: np.ndarray | None
    crop_jpeg: bytes | None = None

    def public(self, names: dict[str, str], include_crop: bool = True) -> dict[str, Any]:
        out = {
            "face_index": self.face_index,
            "bbox": self.bbox,
            "det_score": round(self.det_score, 3),
            "prn": self.prn,
            "name": names.get(self.prn) if self.prn else None,
            "confidence": round(self.confidence, 4) if self.confidence is not None else None,
            "status": self.status,
            "suggestions": [{**s, "name": names.get(s["prn"])} for s in self.suggestions],
            "spoof": self.spoof,
        }
        if include_crop and self.crop_jpeg:
            out["crop"] = to_data_url(self.crop_jpeg)
        return out


def match_faces(img: np.ndarray, faces: list[DetectedFace], candidates: set[str] | None, *,
                threshold: float, margin: float, min_face_px: int, check_spoof: bool = True,
                with_crops: bool = True) -> list[FaceResult]:
    """Match many faces at once with a unique (Hungarian) assignment."""
    settings = get_settings()
    index = face_service.refresh_index()
    usable = [i for i, f in enumerate(faces) if f.embedding is not None and f.min_side >= min_face_px]
    assignment: dict[int, tuple[str, float]] = {}
    scores = np.zeros((0, 0), dtype=np.float32)
    labels: list[str] = []
    if usable and index.size:
        queries = np.stack([faces[i].embedding for i in usable])
        scores, labels = index.per_student_scores(queries, candidates)
        if labels:
            local = assign_unique(scores, labels, threshold - margin)
            assignment = {usable[r]: v for r, v in local.items()}

    results: list[FaceResult] = []
    for i, face in enumerate(faces):
        prn, conf = assignment.get(i, (None, None))
        status = "TOO_SMALL" if face.min_side < min_face_px else classify(conf, threshold, margin)
        if status == "UNKNOWN":
            prn = None
        suggestions: list[dict[str, Any]] = []
        if i in usable and labels:
            row = scores[usable.index(i)]
            for j in np.argsort(-row)[:3]:
                if row[j] >= threshold - 2 * margin:
                    suggestions.append({"prn": labels[int(j)], "score": round(float(row[j]), 4)})
        spoof = None
        if check_spoof and status in ("MATCHED", "LOW_CONFIDENCE") and face.min_side >= 64:
            spoof = {k: round(v, 3) for k, v in screen_artifact_scores(img, face.bbox).items()}
            if spoof["moire"] > settings.moire_threshold or spoof["glare"] > settings.glare_threshold:
                status = "SPOOF_SUSPECTED"
        crop = encode_jpeg(crop_face(img, face.bbox, size=96), quality=80) if with_crops else None
        results.append(FaceResult(
            face_index=i, bbox=face.bbox_list(), det_score=face.det_score, prn=prn,
            confidence=conf if conf is None else float(conf), status=status, suggestions=suggestions,
            spoof=spoof, embedding=face.embedding, crop_jpeg=crop))
    return results


def match_single(embedding: np.ndarray, candidates: set[str] | None, threshold: float,
                 margin: float) -> tuple[Candidate | None, str, list[Candidate]]:
    index = face_service.refresh_index()
    top = index.top_k(embedding, k=3, candidates=candidates)
    best = top[0] if top else None
    status = classify(best.score if best else None, threshold, margin)
    return best, status, top
