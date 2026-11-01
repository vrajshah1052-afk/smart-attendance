"""Pure unit tests (no database): quality gates, matcher, liveness, crypto, saga runner."""
from __future__ import annotations

import numpy as np
import pytest

from app.core.crypto import EmbeddingCipher
from app.face.liveness import evaluate_liveness, screen_artifact_scores
from app.face.matcher import EmbeddingIndex, assign_unique, classify
from app.face.quality import assess_single_capture
from app.services.saga import InMemoryRecorder, Saga, SagaFailed, SagaStep
from tests.fakes import face, identity, noise_image, variant

QUALITY = dict(min_face_px=80, blur_threshold=60, brightness_min=50, brightness_max=210, min_det_score=0.55)
LIVENESS = dict(min_frames=3, min_yaw_delta=15, ear_closed=0.21, ear_drop_ratio=0.75, static_diff=1.2,
                identity_threshold=0.45, moire_threshold=3.2, glare_threshold=0.12)


# ------------------------------------------------------------------ quality
def test_quality_accepts_good_capture() -> None:
    img = noise_image(1)
    report = assess_single_capture(img, [face(identity(1))], **QUALITY)
    assert report.ok, report.issues


def test_quality_rejects_no_face_and_multiple_faces() -> None:
    img = noise_image(2)
    assert assess_single_capture(img, [], **QUALITY).issues[0] == "NO_FACE"
    two = [face(identity(1)), face(identity(2), bbox=(10, 10, 150, 160))]
    assert assess_single_capture(img, two, **QUALITY).issues == ["MULTIPLE_FACES"]


def test_quality_detects_blur_darkness_and_small_face() -> None:
    dark_flat = np.full((480, 640, 3), 20, dtype=np.uint8)
    report = assess_single_capture(dark_flat, [face(identity(1), bbox=(300, 200, 340, 240))], **QUALITY)
    assert {"FACE_TOO_SMALL", "BLURRY", "TOO_DARK"} <= set(report.issues)


# ------------------------------------------------------------------ matcher
def _index(n_students: int = 30, per: int = 3) -> tuple[EmbeddingIndex, list[np.ndarray]]:
    bases = [identity(1000 + i) for i in range(n_students)]
    items = [(f"P{i:05d}", variant(b, 5000 + i * 10 + j, 0.85)) for i, b in enumerate(bases) for j in range(per)]
    index = EmbeddingIndex(backend="numpy")
    index.build(items, version=1, model="fake")
    return index, bases


def test_index_top1_and_candidate_filter() -> None:
    index, bases = _index()
    assert index.size == 90 and index.student_count == 30
    probe = variant(bases[7], 99, 0.8)
    assert index.top_k(probe, k=1)[0].prn == "P00007"
    # restricting candidates must never return a student outside the roster
    top = index.top_k(probe, k=3, candidates={"P00001", "P00002"})
    assert {c.prn for c in top} <= {"P00001", "P00002"}
    assert top[0].score < 0.3


def test_hungarian_never_assigns_one_student_twice() -> None:
    index, bases = _index()
    # two faces both resemble student 3; the second one resembles student 4 a bit less
    q1 = variant(bases[3], 1, 0.80)
    q2 = (0.75 * variant(bases[3], 2, 0.9) + 0.66 * bases[4]).astype(np.float32)
    q2 /= np.linalg.norm(q2)
    scores, labels = index.per_student_scores(np.stack([q1, q2]))
    assignment = assign_unique(scores, labels, min_score=0.3)
    assert assignment[0][0] == "P00003"
    assert assignment[1][0] == "P00004"


def test_classify_bands() -> None:
    assert classify(0.60, 0.45, 0.08) == "MATCHED"
    assert classify(0.48, 0.45, 0.08) == "LOW_CONFIDENCE"
    assert classify(0.40, 0.45, 0.08) == "POSSIBLE"
    assert classify(0.10, 0.45, 0.08) == "UNKNOWN"
    assert classify(None, 0.45, 0.08) == "UNKNOWN"


# ------------------------------------------------------------------ liveness
def _frames(n: int, base: np.ndarray, *, yaws=None, ears=None, same_image: bool = False):
    imgs, faces = [], []
    for i in range(n):
        imgs.append(noise_image(1 if same_image else 100 + i))
        faces.append([face(variant(base, 300 + i, 0.92), yaw=(yaws[i] if yaws else 0.0),
                           ear=(ears[i] if ears else 0.3))])
    return imgs, faces


def test_liveness_head_turn_passes() -> None:
    imgs, faces = _frames(6, identity(5), yaws=[-25, -15, -5, 5, 15, 25])
    result = evaluate_liveness(imgs, faces, "TURN_HEAD", **LIVENESS)
    assert result.passed, result.reasons


def test_liveness_blink_passes_and_missing_blink_fails() -> None:
    imgs, faces = _frames(6, identity(6), ears=[0.31, 0.30, 0.12, 0.11, 0.30, 0.31])
    assert evaluate_liveness(imgs, faces, "BLINK", **LIVENESS).passed
    imgs, faces = _frames(6, identity(6))
    assert "NO_BLINK" in evaluate_liveness(imgs, faces, "BLINK", **LIVENESS).reasons


def test_liveness_blocks_static_photo() -> None:
    imgs, faces = _frames(6, identity(7), same_image=True)
    result = evaluate_liveness(imgs, faces, "TURN_HEAD", **LIVENESS)
    assert not result.passed
    assert {"STATIC_IMAGE", "NO_HEAD_TURN"} <= set(result.reasons)


def test_liveness_detects_identity_swap() -> None:
    imgs, faces = _frames(6, identity(8), yaws=[-25, -15, -5, 5, 15, 25])
    faces[3] = [face(identity(999), yaw=5)]
    faces[4] = [face(identity(998), yaw=15)]
    assert "IDENTITY_CHANGED" in evaluate_liveness(imgs, faces, "TURN_HEAD", **LIVENESS).reasons


def test_screen_artifacts_flag_periodic_pattern() -> None:
    """A synthetic moire (fine sinusoidal grid like a re-captured LCD) is flagged; noise is not."""
    natural = screen_artifact_scores(noise_image(3), (220, 100, 420, 340))["moire"]
    yy, xx = np.mgrid[0:480, 0:640]
    grid = 128 + 60 * np.sin(xx * 0.9) * np.sin(yy * 0.9)
    screen = np.repeat(grid[..., None], 3, axis=2).astype(np.uint8)
    moire = screen_artifact_scores(screen, (220, 100, 420, 340))["moire"]
    assert natural < 3.2 < moire


# ------------------------------------------------------------------ crypto
def test_embedding_encryption_roundtrip_and_tamper_detection() -> None:
    from cryptography.fernet import Fernet

    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    vec = identity(42)
    token = EmbeddingCipher(old).encrypt(vec)
    assert vec.tobytes() not in token  # not stored in clear
    rotated = EmbeddingCipher(f"{new},{old}")  # key rotation: new primary, old still readable
    assert np.allclose(rotated.decrypt(token), vec)
    tampered = token[:-5] + b"AAAAA"
    with pytest.raises(ValueError):
        rotated.decrypt(tampered)


# ------------------------------------------------------------------ saga
def test_saga_compensates_in_reverse_order() -> None:
    calls: list[str] = []

    def fail(_ctx):
        raise RuntimeError("mongo down")

    saga = Saga("REGISTER", "X", [
        SagaStep("a", lambda c: calls.append("a"), lambda c: calls.append("undo-a")),
        SagaStep("b", lambda c: calls.append("b"), lambda c: calls.append("undo-b")),
        SagaStep("c", fail, lambda c: calls.append("undo-c")),
    ], InMemoryRecorder())
    with pytest.raises(SagaFailed) as info:
        saga.run()
    assert calls == ["a", "b", "undo-b", "undo-a"]
    assert info.value.compensated and info.value.step == "c"
    assert saga.recorder.final[saga.saga_id] == "COMPENSATED"


def test_saga_after_pivot_does_not_compensate() -> None:
    calls: list[str] = []
    recorder = InMemoryRecorder()

    def fail(_ctx):
        raise RuntimeError("purge failed")

    saga = Saga("DELETE", "X", [
        SagaStep("soft", lambda c: calls.append("soft"), lambda c: calls.append("undo-soft")),
        SagaStep("pivot", lambda c: calls.append("pivot"), None, pivot=True),
        SagaStep("purge", fail, None),
    ], recorder)
    with pytest.raises(SagaFailed) as info:
        saga.run()
    assert "undo-soft" not in calls and not info.value.compensated
    assert recorder.final[saga.saga_id] == "FAILED"
