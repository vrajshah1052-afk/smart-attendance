"""Solo late entry: liveness, LATE minutes, duplicates, multiple faces, spoof blocking."""
from __future__ import annotations

import pytest

from app.db.mongo import C, col
from tests.conftest import attendance_row, challenge
from tests.fakes import face, identity, unique_identity, variant

pytestmark = pytest.mark.integration


@pytest.fixture()
def student(register):
    base = unique_identity()
    prn, _ = register(base, name="Late Comer")
    return prn, base


def _late(client, headers, sid, frames, token):
    files = [("frames", (f"f{i}.png", data, "image/png")) for i, data in enumerate(frames)]
    return client.post("/attendance/late", data={"session_id": str(sid), "challenge_token": token},
                       files=files, headers=headers)


def test_late_entry_marks_late_with_minutes(client, teacher_headers, open_session, photos, student) -> None:
    prn, base = student
    sid = open_session(minutes_ago=20, late_after=10)
    ch = challenge(client, teacher_headers)
    res = _late(client, teacher_headers, sid, photos.liveness_frames(base, ch["challenge"]), ch["token"])
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["prn"] == prn and out["status"] == "LATE" and out["liveness"]["passed"]
    assert 19 <= out["late_minutes"] <= 21
    row = attendance_row(sid, prn)
    assert row["status"] == "LATE" and 19 <= row["late_minutes"] <= 21 and row["method"] == "FACE_SOLO"

    # no duplicate marking in the same session
    ch2 = challenge(client, teacher_headers)
    dup = _late(client, teacher_headers, sid, photos.liveness_frames(base, ch2["challenge"]), ch2["token"])
    assert dup.status_code == 409 and dup.json()["code"] == "ALREADY_MARKED"


def test_within_grace_period_is_present(client, teacher_headers, open_session, photos, student) -> None:
    prn, base = student
    sid = open_session(minutes_ago=3, late_after=10)
    ch = challenge(client, teacher_headers)
    res = _late(client, teacher_headers, sid, photos.liveness_frames(base, ch["challenge"]), ch["token"])
    assert res.status_code == 200 and res.json()["status"] == "PRESENT"
    assert attendance_row(sid, prn)["late_minutes"] is None


def test_multiple_faces_rejected(client, teacher_headers, open_session, photos, student) -> None:
    _, base = student
    sid = open_session(minutes_ago=20)
    ch = challenge(client, teacher_headers)
    frames = photos.liveness_frames(base, ch["challenge"])
    frames[2] = photos.photo([face(variant(base, 5)), face(identity(999), bbox=(20, 20, 150, 170))])
    res = _late(client, teacher_headers, sid, frames, ch["token"])
    assert res.status_code == 422 and res.json()["code"] == "MULTIPLE_FACES"


def test_no_face_rejected(client, teacher_headers, open_session, photos) -> None:
    sid = open_session(minutes_ago=20)
    ch = challenge(client, teacher_headers)
    res = _late(client, teacher_headers, sid, [photos.photo([]) for _ in range(4)], ch["token"])
    assert res.status_code == 422 and res.json()["code"] == "NO_FACE"


def test_unknown_person_rejected(client, teacher_headers, open_session, photos) -> None:
    sid = open_session(minutes_ago=20)
    ch = challenge(client, teacher_headers)
    stranger = unique_identity()
    res = _late(client, teacher_headers, sid, photos.liveness_frames(stranger, ch["challenge"]), ch["token"])
    assert res.status_code == 404 and res.json()["code"] == "UNKNOWN_FACE"


def test_printed_photo_spoof_is_blocked_and_logged(client, teacher_headers, open_session, photos, student) -> None:
    prn, base = student
    sid = open_session(minutes_ago=20)
    before = col(C.SPOOF_ATTEMPTS).count_documents({})
    ch = challenge(client, teacher_headers)
    res = _late(client, teacher_headers, sid, photos.liveness_frames(base, ch["challenge"], static=True),
                ch["token"])
    assert res.status_code == 403, res.text
    body = res.json()
    assert body["code"] == "LIVENESS_FAILED" and "STATIC_IMAGE" in body["details"]["reasons"]
    assert col(C.SPOOF_ATTEMPTS).count_documents({}) == before + 1
    attempt = col(C.SPOOF_ATTEMPTS).find_one(sort=[("created_at", -1)])
    assert attempt["prn"] == prn and attempt["endpoint"] == "/attendance/late"
    assert attendance_row(sid, prn) is None


def test_liveness_challenge_cannot_be_replayed(client, teacher_headers, open_session, photos, student) -> None:
    _, base = student
    sid = open_session(minutes_ago=20)
    ch = challenge(client, teacher_headers)
    frames = photos.liveness_frames(base, ch["challenge"], static=True)
    assert _late(client, teacher_headers, sid, frames, ch["token"]).status_code == 403
    replay = _late(client, teacher_headers, sid, frames, ch["token"])
    assert replay.status_code == 400 and replay.json()["code"] == "CHALLENGE_REUSED"


def test_challenge_is_required(client, teacher_headers, open_session, photos, student) -> None:
    _, base = student
    sid = open_session(minutes_ago=20)
    res = _late(client, teacher_headers, sid, photos.liveness_frames(base, "TURN_HEAD"), "")
    assert res.status_code == 400 and res.json()["code"] in ("CHALLENGE_REQUIRED", "CHALLENGE_INVALID")
