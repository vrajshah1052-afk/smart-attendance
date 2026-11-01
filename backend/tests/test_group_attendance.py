"""Group photo: analyse -> confirm (atomic), duplicates, double submission, live feed."""
from __future__ import annotations

import pytest
from sqlalchemy import exc as sa_exc
from sqlalchemy import text

from app.db.mysql import fetch_scalar, transaction
from tests.conftest import attendance_row
from tests.fakes import data_url, face, identity, unique_identity, variant

pytestmark = pytest.mark.integration

BOXES = [(40, 120, 180, 280), (240, 120, 380, 280), (440, 120, 580, 280)]


@pytest.fixture()
def two_students(register):
    a, b = unique_identity(), unique_identity()
    prn_a, _ = register(a, name="Group Alpha")
    prn_b, _ = register(b, name="Group Beta")
    return (prn_a, a), (prn_b, b)


def _group_photo(photos, a, b):
    return photos.photo([face(variant(a, 1, 0.80), BOXES[0]), face(variant(b, 2, 0.70), BOXES[1]),
                         face(identity(5555), BOXES[2])])


def _analyse(client, headers, session_id, photo):
    return client.post("/attendance/group", data={"session_id": str(session_id)},
                       files={"photo": ("class.png", photo, "image/png")}, headers=headers)


def test_group_analysis_and_atomic_confirm(client, teacher_headers, open_session, photos, two_students) -> None:
    (prn_a, a), (prn_b, b) = two_students
    sid = open_session()
    res = _analyse(client, teacher_headers, sid, _group_photo(photos, a, b))
    assert res.status_code == 200, res.text
    out = res.json()
    statuses = {f["prn"]: f["status"] for f in out["faces"] if f["prn"]}
    assert statuses == {prn_a: "MATCHED", prn_b: "MATCHED"}
    assert out["summary"]["UNKNOWN"] == 1
    assert out["annotated_image"].startswith("data:image/jpeg;base64,")
    unknown = [f for f in out["faces"] if f["status"] == "UNKNOWN"][0]
    assert unknown["crop"].startswith("data:image/jpeg")

    # nothing is written before the teacher confirms
    assert attendance_row(sid, prn_a) is None

    res = client.post("/attendance/group/confirm", json={"draft_id": out["draft_id"], "session_id": sid,
                                                          "prns": [prn_a, prn_b]}, headers=teacher_headers)
    assert res.status_code == 200, res.text
    assert res.json()["inserted"] == 2
    row = attendance_row(sid, prn_a)
    assert row["status"] == "PRESENT" and row["method"] == "FACE_GROUP" and 0.5 < row["confidence"] <= 1

    # double submission of the same draft
    again = client.post("/attendance/group/confirm", json={"draft_id": out["draft_id"], "session_id": sid,
                                                            "prns": [prn_a, prn_b]}, headers=teacher_headers)
    assert again.status_code == 409 and again.json()["code"] == "ALREADY_COMMITTED"

    # a second photo of the same class marks nobody twice
    res2 = _analyse(client, teacher_headers, sid, _group_photo(photos, a, b))
    draft2 = res2.json()
    assert {r["prn"]: r["already_marked"] for r in draft2["roster"]}[prn_a] == "PRESENT"
    res3 = client.post("/attendance/group/confirm", json={"draft_id": draft2["draft_id"], "session_id": sid,
                                                           "prns": [prn_a]}, headers=teacher_headers)
    assert res3.json()["inserted"] == 0 and res3.json()["duplicates"] == [prn_a]


def test_confirm_is_all_or_nothing(client, teacher_headers, open_session, photos, two_students, register) -> None:
    (prn_a, a), (prn_b, b) = two_students
    outsider, _ = register(unique_identity(), year=3)            # enrolled in TST301 only
    sid = open_session()
    draft = _analyse(client, teacher_headers, sid, _group_photo(photos, a, b)).json()
    res = client.post("/attendance/group/confirm", json={
        "draft_id": draft["draft_id"], "session_id": sid, "prns": [prn_a, prn_b],
        "manual": [{"prn": outsider, "reason": "teacher saw him at the back"}]}, headers=teacher_headers)
    assert res.status_code == 400 and res.json()["code"] == "STUDENT_NOT_ENROLLED"
    # rollback: the two valid students were NOT marked either
    assert attendance_row(sid, prn_a) is None and attendance_row(sid, prn_b) is None

    # the draft was unlocked, so the corrected list can be submitted
    ok = client.post("/attendance/group/confirm", json={
        "draft_id": draft["draft_id"], "session_id": sid, "prns": [prn_a],
        "manual": [{"prn": prn_b, "reason": "face hidden behind a classmate"}]}, headers=teacher_headers)
    assert ok.status_code == 200 and ok.json()["inserted"] == 2
    assert attendance_row(sid, prn_b)["method"] == "MANUAL"
    with transaction() as conn:
        audited = fetch_scalar(conn, """SELECT COUNT(*) FROM audit_log WHERE table_name = 'attendance'
                                        AND action = 'INSERT' AND reason LIKE '%%hidden behind%%'""")
    assert audited == 1


def test_unrecognised_prn_cannot_be_ticked(client, teacher_headers, open_session, photos, two_students) -> None:
    (prn_a, a), (prn_b, b) = two_students
    sid = open_session()
    only_a = photos.photo([face(variant(a, 9, 0.8), BOXES[0])])
    draft = _analyse(client, teacher_headers, sid, only_a).json()
    res = client.post("/attendance/group/confirm", json={"draft_id": draft["draft_id"], "session_id": sid,
                                                          "prns": [prn_a, prn_b]}, headers=teacher_headers)
    assert res.status_code == 400 and res.json()["code"] == "NOT_RECOGNISED"


def test_session_must_be_open(client, teacher_headers, open_session, photos, two_students) -> None:
    (_, a), (_, b) = two_students
    sid = open_session(status="SCHEDULED")
    res = _analyse(client, teacher_headers, sid, _group_photo(photos, a, b))
    assert res.status_code == 409 and res.json()["code"] == "SESSION_NOT_OPEN"
    assert _analyse(client, teacher_headers, sid, photos.photo([])).status_code == 409


def test_no_faces_detected(client, teacher_headers, open_session, photos) -> None:
    sid = open_session()
    res = _analyse(client, teacher_headers, sid, photos.photo([]))
    assert res.status_code == 422 and res.json()["code"] == "NO_FACES_DETECTED"


def test_unique_constraint_blocks_duplicate_rows(open_session, two_students) -> None:
    (prn_a, _), _ = two_students
    sid = open_session()
    sql = text("""INSERT INTO attendance (session_id, prn, status, method, confidence)
                  VALUES (:s, :p, 'PRESENT', 'QR', NULL)""")
    with transaction() as conn:
        conn.execute(sql, {"s": sid, "p": prn_a})
    with pytest.raises(sa_exc.IntegrityError) as info:
        with transaction() as conn:
            conn.execute(sql, {"s": sid, "p": prn_a})
    assert info.value.orig.args[0] == 1062


def test_close_session_marks_absentees(client, teacher_headers, open_session, two_students) -> None:
    (prn_a, _), (prn_b, _) = two_students
    sid = open_session()
    with transaction() as conn:
        conn.execute(text("""INSERT INTO attendance (session_id, prn, status, method)
                             VALUES (:s, :p, 'PRESENT', 'QR')"""), {"s": sid, "p": prn_a})
    res = client.post(f"/sessions/{sid}/close", headers=teacher_headers)
    assert res.status_code == 200, res.text
    assert res.json()["absent_marked"] >= 1
    assert attendance_row(sid, prn_b)["status"] == "ABSENT"
    assert client.post(f"/sessions/{sid}/close", headers=teacher_headers).status_code == 409


def test_live_websocket_feed(client, teacher_headers, open_session, photos, two_students) -> None:
    (prn_a, a), _ = two_students
    sid = open_session()
    token = teacher_headers["Authorization"].split()[1]
    frame = photos.photo([face(variant(a, 77, 0.8), BOXES[0])])
    with client.websocket_connect(f"/ws/live?token={token}") as ws:
        assert ws.receive_json()["type"] == "hello"
        ws.send_json({"type": "ping"})
        assert ws.receive_json()["type"] == "pong"
        ws.send_json({"type": "frame", "session_id": sid, "image": data_url(frame)})
        msg = ws.receive_json()
        while msg["type"] != "recognition":
            msg = ws.receive_json()
        assert msg["faces"][0]["prn"] == prn_a
        assert msg["seen"][0]["prn"] == prn_a and msg["draft_id"]
    res = client.post("/attendance/group/confirm", json={"draft_id": msg["draft_id"], "session_id": sid,
                                                          "prns": [prn_a]}, headers=teacher_headers)
    assert res.status_code == 200 and res.json()["inserted"] == 1
    assert attendance_row(sid, prn_a)["method"] == "FACE_LIVE"


def test_websocket_rejects_bad_token(client) -> None:
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/live?token=garbage") as ws:
            ws.receive_json()
