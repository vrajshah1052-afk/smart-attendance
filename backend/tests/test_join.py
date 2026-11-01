"""Class codes: course QR poster, joining a course, self-registration from the code."""
from __future__ import annotations

import pytest

from app.db.mysql import fetch_one, fetch_scalar, transaction
from tests.conftest import new_prn
from tests.fakes import identity

pytestmark = pytest.mark.integration


def _poster(client, headers, course_id: int) -> dict:
    res = client.get(f"/courses/{course_id}/join", headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


def _enrolled(prn: str, course_id: int) -> bool:
    with transaction() as conn:
        return bool(fetch_scalar(conn, "SELECT COUNT(*) FROM enrollments WHERE prn = :p AND course_id = :c",
                                 {"p": prn, "c": course_id}))


def test_poster_code_is_stable_and_public_preview_needs_no_login(client, academic, teacher_headers) -> None:
    course_id = academic["courses"]["TST201"]
    first = _poster(client, teacher_headers, course_id)
    assert len(first["join_code"]) == 6 and first["join_code"].isalnum()
    assert first["url"].endswith(f"/join/{first['join_code']}")
    assert first["qr_png"].startswith("data:image/png;base64,")
    assert _poster(client, teacher_headers, course_id)["join_code"] == first["join_code"]

    res = client.get(f"/join/{first['join_code'].lower()}")  # codes are case-insensitive
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["course"]["code"] == "TST201" and body["join_open"] is True
    assert body["divisions"] == ["A", "B"]
    assert client.get("/join/ZZZZZZ").json()["code"] == "JOIN_CODE_INVALID"


def test_student_joins_course_with_code(client, academic, teacher_headers, admin_headers, register, login) -> None:
    course_id = academic["courses"]["TST201"]
    code = _poster(client, teacher_headers, course_id)["join_code"]
    prn, reg = register(identity(501), year=3)  # year 3: auto-enrolled in TST301 only
    assert not _enrolled(prn, course_id)
    headers = login(prn, reg["temp_password"])

    res = client.post(f"/join/{code}", headers=headers)
    assert res.status_code == 200, res.text
    assert res.json()["joined"] is True and _enrolled(prn, course_id)
    again = client.post(f"/join/{code}", headers=headers).json()
    assert again["joined"] is False and again["already_enrolled"] is True

    assert client.post(f"/join/{code}", headers=admin_headers).status_code == 403
    assert client.post(f"/join/{code}").status_code == 401


def test_closed_or_reset_code_stops_joining(client, academic, teacher_headers, register, login) -> None:
    course_id = academic["courses"]["TST202"]
    code = _poster(client, teacher_headers, course_id)["join_code"]
    prn, reg = register(identity(502), year=3)
    headers = login(prn, reg["temp_password"])

    closed = client.put(f"/courses/{course_id}/join", json={"open": False}, headers=teacher_headers)
    assert closed.status_code == 200 and closed.json()["join_open"] is False
    res = client.post(f"/join/{code}", headers=headers)
    assert res.status_code == 409 and res.json()["code"] == "JOIN_CLOSED"
    assert client.get(f"/join/{code}").json()["join_open"] is False
    client.put(f"/courses/{course_id}/join", json={"open": True}, headers=teacher_headers)

    new_code = client.post(f"/courses/{course_id}/join/reset", headers=teacher_headers).json()["join_code"]
    assert new_code != code
    assert client.post(f"/join/{code}", headers=headers).status_code == 404
    assert client.post(f"/join/{new_code}", headers=headers).json()["joined"] is True


def test_new_student_signs_up_from_class_code(client, academic, teacher_headers, photos) -> None:
    course_id = academic["courses"]["TST201"]
    code = _poster(client, teacher_headers, course_id)["join_code"]
    prn = new_prn("JN")
    form = {"name": "Riya Join", "prn": prn, "email": f"{prn.lower()}@student.example.org", "phone": "9876500001",
            "division": "B", "roll_no": "77", "password": "JoinPass12", "consent": "true"}
    files = [("photos", (f"p{i}.png", data, "image/png")) for i, data in enumerate(photos.enrolment_set(identity(503)))]

    res = client.post(f"/join/{code}/register", data=form, files=files)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["access_token"] and body["user"]["role"] == "STUDENT" and body["user"]["prn"] == prn
    assert body["user"]["must_change_password"] is False and body["embeddings_stored"] == 5
    assert _enrolled(prn, course_id)
    with transaction() as conn:
        student = fetch_one(conn, """SELECT s.face_status, d.name AS division, d.year_of_study FROM students s
                                     JOIN divisions d ON d.division_id = s.division_id WHERE s.prn = :p""", {"p": prn})
        saga = fetch_one(conn, "SELECT status, created_by FROM saga_log WHERE subject = :p", {"p": prn})
    assert student == {"face_status": "ENROLLED", "division": "B", "year_of_study": 2}
    assert saga == {"status": "COMPLETED", "created_by": None}
    # the chosen password works straight away
    assert client.post("/auth/login", data={"username": prn, "password": "JoinPass12"}).status_code == 200

    # same face again under another PRN is blocked by the duplicate check
    form2 = {**form, "prn": new_prn("JN"), "email": "other.join@student.example.org", "roll_no": "78"}
    files2 = [("photos", (f"p{i}.png", d, "image/png")) for i, d in enumerate(photos.enrolment_set(identity(503)))]
    dup = client.post(f"/join/{code}/register", data=form2, files=files2)
    assert dup.status_code == 409 and dup.json()["code"] == "DUPLICATE_FACE"
    assert prn not in dup.text  # whose face it matched stays hidden from an anonymous caller

    check = client.post(f"/join/{code}/quality-check",
                        files={"photo": ("p.png", photos.enrolment_set(identity(503))[0], "image/png")})
    assert check.status_code == 200, check.text
    assert check.json()["duplicate_of"] == {"registered": True}
