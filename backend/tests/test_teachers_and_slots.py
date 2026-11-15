"""Teacher accounts (admin-provisioned, employee code as the login) and
sessions snapped to the clock hour."""
from __future__ import annotations

import datetime as dt

import pytest

from app.core.utils import normalise_username
from app.db.mysql import fetch_one, transaction
from app.routers.academic import hour_slot

pytestmark = pytest.mark.integration


# ------------------------------------------------------------------ pure
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("VIT@001", "VIT@001"),
        ("vit@001", "VIT@001"),  # codes are case-insensitive at the sign-in box
        ("  Vit@001 ", "VIT@001"),
        ("admin@Example.ORG", "admin@example.org"),  # a real e-mail still folds down
        ("12310001", "12310001"),
        ("TST-LOCK", "TST-LOCK"),
    ],
)
def test_employee_codes_are_not_mistaken_for_emails(raw, expected) -> None:
    assert normalise_username(raw) == expected


@pytest.mark.parametrize(
    "at, start, end",
    [
        ((8, 43), dt.time(8, 0), dt.time(9, 0)),
        ((8, 0), dt.time(8, 0), dt.time(9, 0)),
        ((0, 5), dt.time(0, 0), dt.time(1, 0)),
        ((23, 17), dt.time(23, 0), dt.time(23, 59, 59)),  # stays on the same date
    ],
)
def test_hour_slot(at, start, end) -> None:
    assert hour_slot(dt.datetime(2026, 11, 15, at[0], at[1], 31)) == (start, end)


# ------------------------------------------------------------------ teachers
def test_admin_creates_the_teacher_and_picks_the_password(client, academic, admin_headers) -> None:
    body = {"employee_code": "vit@901", "full_name": "Renuka Test", "email": "renuka.test@vit.edu",
            "branch": "CS", "password": "renuka.vit@901"}
    res = client.post("/teachers", json=body, headers=admin_headers)
    assert res.status_code == 201, res.text
    assert res.json()["username"] == "VIT@901" and res.json()["temp_password"] is None

    # the code is the login, in either case; the e-mail is not
    assert client.post("/auth/login", data={"username": "VIT@901", "password": "renuka.vit@901"}).status_code == 200
    assert client.post("/auth/login", data={"username": "vit@901", "password": "renuka.vit@901"}).status_code == 200
    assert client.post("/auth/login", data={"username": "renuka.test@vit.edu", "password": "renuka.vit@901"}).status_code == 401

    me = client.post("/auth/login", data={"username": "VIT@901", "password": "renuka.vit@901"}).json()
    assert me["user"]["role"] == "TEACHER" and me["user"]["teacher_id"]

    # the same code cannot be taken twice
    dup = client.post("/teachers", json={**body, "email": "other.test@vit.edu"}, headers=admin_headers)
    assert dup.status_code == 409 and dup.json()["code"] == "EMPLOYEE_CODE_EXISTS"


def test_teachers_cannot_make_their_own_account(client, academic, teacher_headers) -> None:
    body = {"employee_code": "VIT@902", "full_name": "Self Made", "email": "self.made@vit.edu",
            "branch": "CS", "password": "SelfMade12"}
    assert client.post("/teachers", json=body, headers=teacher_headers).status_code == 403
    assert client.post("/teachers", json=body).status_code == 401
    # and the public student sign-up cannot mint staff either
    assert client.get("/signup").json()["enabled"] is True
    assert client.post("/signup", data={**body, "prn": "VIT902", "phone": "9876500099", "year": "2",
                                        "division": "A", "roll_no": "199", "name": "Self Made",
                                        "consent": "true"}).status_code in (409, 422)


def test_admin_can_reset_a_forgotten_password(client, academic, admin_headers) -> None:
    created = client.post("/teachers", json={"employee_code": "VIT@903", "full_name": "Reset Me",
                                             "email": "reset.me@vit.edu", "branch": "CS",
                                             "password": "FirstPass1"}, headers=admin_headers)
    teacher_id = created.json()["teacher_id"]

    res = client.post(f"/teachers/{teacher_id}/password", json={"password": "SecondPass2"}, headers=admin_headers)
    assert res.status_code == 200 and res.json()["username"] == "VIT@903"
    assert client.post("/auth/login", data={"username": "VIT@903", "password": "FirstPass1"}).status_code == 401
    assert client.post("/auth/login", data={"username": "VIT@903", "password": "SecondPass2"}).status_code == 200

    # no password given: a one-time one comes back and must be changed
    generated = client.post(f"/teachers/{teacher_id}/password", json={}, headers=admin_headers).json()
    assert generated["temp_password"]
    out = client.post("/auth/login", data={"username": "VIT@903", "password": generated["temp_password"]})
    assert out.status_code == 200 and out.json()["user"]["must_change_password"] is True

    assert client.post(f"/teachers/{teacher_id}/password", json={"password": "x"},
                       headers=admin_headers).status_code == 422  # too weak
    assert client.post("/teachers/999999/password", json={"password": "Whatever12"},
                       headers=admin_headers).status_code == 404


# ------------------------------------------------------------------ sessions
def test_starting_a_lecture_now_records_the_clock_hour(client, academic, teacher_headers) -> None:
    course_id = academic["courses"]["TST201"]
    res = client.post("/sessions/now", json={"course_id": course_id, "room": "A-101"}, headers=teacher_headers)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "OPEN"

    with transaction() as conn:
        now = fetch_one(conn, "SELECT NOW() AS n")["n"]
    start_h, end_h = hour_slot(now)
    # the lecture is filed under the hour it was started in, on the minute
    assert body["start_time"].startswith(start_h.strftime("%H:%M"))
    assert body["end_time"].startswith(end_h.strftime("%H:%M"))
    assert body["start_time"][3:5] == "00"

    # starting the same course again in the same hour reuses the slot
    again = client.post("/sessions/now", json={"course_id": course_id}, headers=teacher_headers)
    assert again.status_code == 201 and again.json()["session_id"] == body["session_id"]

    assert client.post("/sessions/now", json={"course_id": 999999}, headers=teacher_headers).status_code == 404
    assert client.post("/sessions/now", json={"course_id": course_id}).status_code == 401
