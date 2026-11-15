"""Student registration saga, quality gates and duplicate protection."""
from __future__ import annotations

import pytest

from app.db.mongo import C, col
from app.db.mysql import fetch_one, fetch_scalar, transaction
from tests.conftest import new_prn
from tests.fakes import face, identity, png, variant

pytestmark = pytest.mark.integration


def test_register_student_stores_profile_and_encrypted_embeddings(client, academic, register, login) -> None:
    base = identity(1)
    prn, body = register(base, name="Aarav Test")
    assert body["embeddings_stored"] == 5
    assert body["courses_enrolled"] == 2          # auto-enrolled in TST201 + TST202 (CS year 2)
    assert body["student"]["face_status"] == "ENROLLED"
    assert body["temp_password"]

    with transaction() as conn:
        student = fetch_one(conn, "SELECT * FROM students WHERE prn = :p", {"p": prn})
        saga = fetch_one(conn, "SELECT status FROM saga_log WHERE subject = :p AND saga_type = 'REGISTER'", {"p": prn})
    assert student and student["consent_given"] == 1
    assert saga["status"] == "COMPLETED"

    docs = list(col(C.FACE_EMBEDDINGS).find({"prn": prn}))
    assert len(docs) == 5
    raw = base.astype("<f4").tobytes()[:64]
    assert all(raw not in bytes(d["embedding_enc"]) for d in docs)  # encrypted at rest
    assert {d["pose"] for d in docs} >= {"left", "front", "right"}

    # the student can log in with the one-time password and must change it
    res = client.post("/auth/login", data={"username": prn.lower(), "password": body["temp_password"]})
    assert res.status_code == 200 and res.json()["user"]["must_change_password"] is True


def test_consent_is_mandatory(client, academic, register) -> None:
    _, body = register(identity(2), consent="false", expect=422)
    assert body["code"] == "VALIDATION_ERROR"


def test_requires_minimum_number_of_photos(client, academic, register, photos) -> None:
    _, body = register(identity(3), photos_list=photos.enrolment_set(identity(3), n=3), expect=422)
    assert body["code"] == "PHOTO_COUNT"


def test_rejects_bad_quality_photos(client, academic, register, photos, fake_engine) -> None:
    base = identity(4)
    good = photos.enrolment_set(base, n=3)
    # no face, two faces, too small + dark
    no_face = photos.photo([])
    two = photos.photo([face(variant(base, 1)), face(identity(77), bbox=(20, 20, 160, 180))])
    import numpy as np
    dark = np.full((480, 640, 3), 15, dtype=np.uint8)
    fake_engine.register(dark, [face(variant(base, 2), bbox=(300, 200, 350, 250))])
    _, body = register(base, photos_list=good + [no_face, two, png(dark)], expect=422)
    assert body["code"] == "PHOTO_QUALITY"
    issues = {i for p in body["details"]["photos"] for i in p["issues"]}
    assert {"NO_FACE", "MULTIPLE_FACES", "FACE_TOO_SMALL", "TOO_DARK"} <= issues


def test_duplicate_prn_rejected(client, academic, register) -> None:
    prn, _ = register(identity(5))
    _, body = register(identity(6), prn=prn, expect=409)
    assert body["code"] == "PRN_EXISTS"


def test_same_face_different_prn_is_blocked(client, academic, register) -> None:
    base = identity(7)
    original, _ = register(base)
    other = new_prn()
    _, body = register(base, prn=other, expect=409)
    assert body["code"] == "DUPLICATE_FACE"
    assert body["details"]["existing_prn"] == original
    with transaction() as conn:
        assert fetch_scalar(conn, "SELECT COUNT(*) FROM students WHERE prn = :p", {"p": other}) == 0


def test_pose_variety_required(client, academic, register, photos) -> None:
    base = identity(8)
    frontal_only = [photos.photo([face(variant(base, 900 + i), yaw=0.0)]) for i in range(5)]
    _, body = register(base, photos_list=frontal_only, expect=422)
    assert body["code"] == "POSE_VARIETY"


def test_quality_check_endpoint_reports_pose_and_duplicate(client, academic, register, photos, admin_headers) -> None:
    base = identity(9)
    prn, _ = register(base)
    probe = photos.photo([face(variant(base, 4242, 0.9), yaw=-20)])
    res = client.post("/students/quality-check", files={"photo": ("p.png", probe, "image/png")},
                      headers=admin_headers)
    assert res.status_code == 200
    out = res.json()
    assert out["accepted"] and out["pose"] == "left"
    assert out["duplicate_of"]["prn"] == prn


def test_invalid_image_and_unknown_division(client, academic, register, admin_headers) -> None:
    res = client.post("/students/quality-check", files={"photo": ("x.png", b"not an image", "image/png")},
                      headers=admin_headers)
    assert res.status_code == 400 and res.json()["code"] == "INVALID_IMAGE"
    _, body = register(identity(10), division="Z", expect=422)
    assert body["code"] == "UNKNOWN_DIVISION"
