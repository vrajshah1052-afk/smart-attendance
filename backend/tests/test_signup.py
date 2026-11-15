"""Public self sign-up from the login page and the admin approval gate."""
from __future__ import annotations

import pytest

from app.db.mysql import fetch_one, fetch_scalar, transaction
from tests.conftest import new_prn
from tests.fakes import identity

pytestmark = pytest.mark.integration


def _form(prn: str, **overrides) -> dict:
    form = {"name": "Riya Kadam", "prn": prn, "email": f"{prn.lower()}@student.example.org",
            "phone": "9876500010", "branch": "CS", "year": "2", "division": "A", "roll_no": "121",
            "password": "SignUpPass1", "consent": "true"}
    form.update({k: str(v) for k, v in overrides.items()})
    return form


def _files(photos, base):
    return [("photos", (f"p{i}.png", data, "image/png")) for i, data in enumerate(photos.enrolment_set(base))]


def _face_status(prn: str) -> str | None:
    with transaction() as conn:
        return fetch_scalar(conn, "SELECT face_status FROM students WHERE prn = :p", {"p": prn})


def test_options_are_public_and_describe_the_form(client, academic) -> None:
    res = client.get("/signup")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["enabled"] is True and body["requires_approval"] is True
    assert body["min_photos"] >= 1 and body["max_photos"] >= body["min_photos"]
    cs = next(b for b in body["branches"] if b["code"] == "CS")
    assert cs["years"]["2"] == ["A", "B"] and cs["years"]["3"] == ["A"]


def test_signup_is_held_until_an_admin_approves_it(client, academic, admin_headers, photos) -> None:
    prn = new_prn("SU")
    res = client.post("/signup", data=_form(prn, roll_no=131), files=_files(photos, identity(601)))
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["prn"] == prn and body["pending_approval"] is True and body["embeddings_stored"] == 5
    assert "access_token" not in body
    assert _face_status(prn) == "PENDING_APPROVAL"

    # signing up alone enrols the student in nothing: they pick their courses after approval
    with transaction() as conn:
        assert fetch_scalar(conn, "SELECT COUNT(*) FROM enrollments WHERE prn = :p", {"p": prn}) == 0

    held = client.post("/auth/login", data={"username": prn, "password": "SignUpPass1"})
    assert held.status_code == 403 and held.json()["code"] == "PENDING_APPROVAL"

    pending = client.get("/students/pending", headers=admin_headers)
    assert pending.status_code == 200
    row = next(i for i in pending.json()["items"] if i["prn"] == prn)
    assert row["branch"] == "CS" and row["year"] == 2 and row["division"] == "A"

    approved = client.post(f"/students/{prn}/approve", headers=admin_headers)
    assert approved.status_code == 200 and approved.json()["face_status"] == "ENROLLED"
    assert client.post("/auth/login", data={"username": prn, "password": "SignUpPass1"}).status_code == 200
    assert prn not in [i["prn"] for i in client.get("/students/pending", headers=admin_headers).json()["items"]]
    # approving again is refused
    assert client.post(f"/students/{prn}/approve", headers=admin_headers).json()["code"] == "NOT_PENDING_APPROVAL"


def test_a_wrong_password_is_still_refused_before_the_gate(client, academic, admin_headers, photos) -> None:
    """Regression: the approval check must not short-circuit verify_password()."""
    prn = new_prn("SU")
    assert client.post("/signup", data=_form(prn, roll_no=132),
                       files=_files(photos, identity(602))).status_code == 201
    wrong = client.post("/auth/login", data={"username": prn, "password": "NotTheOne9"})
    assert wrong.status_code == 401 and wrong.json()["code"] == "INVALID_CREDENTIALS"

    client.post(f"/students/{prn}/approve", headers=admin_headers)
    wrong_again = client.post("/auth/login", data={"username": prn, "password": "NotTheOne9"})
    assert wrong_again.status_code == 401 and wrong_again.json()["code"] == "INVALID_CREDENTIALS"


def test_rejecting_erases_the_account_and_its_face_templates(client, academic, admin_headers, photos) -> None:
    prn = new_prn("SU")
    assert client.post("/signup", data=_form(prn, roll_no=133),
                       files=_files(photos, identity(603))).status_code == 201

    assert client.post(f"/students/{prn}/reject", json={"reason": "no"},
                       headers=admin_headers).status_code == 422  # reason too short
    res = client.post(f"/students/{prn}/reject", json={"reason": "not in our division"}, headers=admin_headers)
    assert res.status_code == 200 and res.json()["rejected"] is True

    with transaction() as conn:
        assert fetch_one(conn, "SELECT prn FROM students WHERE prn = :p", {"p": prn}) is None
        assert fetch_one(conn, "SELECT user_id FROM users WHERE username = :p", {"p": prn}) is None
    assert client.post("/auth/login", data={"username": prn, "password": "SignUpPass1"}).status_code == 401
    # the same face can sign up again afterwards
    retry = client.post("/signup", data=_form(new_prn("SU"), roll_no=134, email="again@student.example.org"),
                        files=_files(photos, identity(603)))
    assert retry.status_code == 201, retry.text


def test_only_admins_work_the_queue(client, academic, teacher_headers, photos) -> None:
    prn = new_prn("SU")
    assert client.post("/signup", data=_form(prn, roll_no=135),
                       files=_files(photos, identity(604))).status_code == 201
    assert client.get("/students/pending").status_code == 401
    assert client.get("/students/pending", headers=teacher_headers).status_code == 403
    assert client.post(f"/students/{prn}/approve", headers=teacher_headers).status_code == 403
    assert client.post(f"/students/{prn}/reject", json={"reason": "not allowed"},
                       headers=teacher_headers).status_code == 403


def test_signup_rejects_bad_data_and_duplicate_faces(client, academic, photos) -> None:
    prn = new_prn("SU")
    bad = client.post("/signup", data=_form(prn, email="not-an-email", roll_no=141),
                      files=_files(photos, identity(605)))
    assert bad.status_code == 422 and bad.json()["code"] == "VALIDATION_ERROR"

    no_consent = client.post("/signup", data=_form(prn, consent="false", roll_no=142),
                             files=_files(photos, identity(605)))
    assert no_consent.status_code == 422

    unknown = client.post("/signup", data=_form(prn, division="Z", roll_no=143),
                          files=_files(photos, identity(605)))
    assert unknown.status_code == 422 and unknown.json()["code"] == "UNKNOWN_DIVISION"

    assert client.post("/signup", data=_form(prn, roll_no=144),
                       files=_files(photos, identity(606))).status_code == 201
    dup = client.post("/signup", data=_form(new_prn("SU"), email="dup@student.example.org", roll_no=145),
                      files=_files(photos, identity(606)))
    assert dup.status_code == 409 and dup.json()["code"] == "DUPLICATE_FACE"
    assert prn not in dup.text  # an anonymous caller does not learn whose face it matched
