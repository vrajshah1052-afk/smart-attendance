"""Overrides (trigger audit), student scope, QR fallback, exports, analytics, lockout."""
from __future__ import annotations

import pytest

from app.db.mysql import fetch_one, transaction
from app.services.challenges import qr_code_for
from tests.conftest import attendance_row
from tests.fakes import unique_identity

pytestmark = pytest.mark.integration


@pytest.fixture()
def student(register):
    prn, _ = register(unique_identity(), name="Report Student", password="StudentPass1")
    return prn


def test_teacher_override_is_audited_by_trigger(client, teacher_headers, open_session, student) -> None:
    sid = open_session()
    res = client.post("/overrides", json={"session_id": sid, "prn": student, "requested_status": "PRESENT",
                                          "reason": "Camera failed, verified roll call"}, headers=teacher_headers)
    assert res.status_code == 201, res.text
    assert res.json()["status"] == "APPROVED"
    assert attendance_row(sid, student)["method"] == "MANUAL"
    with transaction() as conn:
        audit = fetch_one(conn, """SELECT * FROM audit_log WHERE table_name = 'attendance' AND action = 'OVERRIDE'
                                   ORDER BY audit_id DESC LIMIT 1""")
    assert audit["reason"] == "Camera failed, verified roll call" and audit["changed_by"] is not None


def test_student_requests_and_teacher_approves(client, teacher_headers, open_session, student, login) -> None:
    sid = open_session()
    headers = login(student, "StudentPass1")
    req = client.post("/overrides", json={"session_id": sid, "prn": student, "requested_status": "PRESENT",
                                          "reason": "I was present at the back bench"}, headers=headers)
    assert req.status_code == 201 and req.json()["status"] == "PENDING"
    dup = client.post("/overrides", json={"session_id": sid, "prn": student, "requested_status": "PRESENT",
                                          "reason": "asking again"}, headers=headers)
    assert dup.status_code == 409
    oid = req.json()["override_id"]
    assert client.post(f"/overrides/{oid}/approve", json={"note": "ok"}, headers=headers).status_code == 403
    ok = client.post(f"/overrides/{oid}/approve", json={"note": "verified"}, headers=teacher_headers)
    assert ok.status_code == 200 and ok.json()["status"] == "APPROVED"
    again = client.post(f"/overrides/{oid}/approve", json={}, headers=teacher_headers)
    assert again.status_code == 409 and again.json()["code"] == "OVERRIDE_ALREADY_RESOLVED"
    # update path of an existing row: ABSENT -> LATE with explicit minutes is recomputed by trigger
    res = client.post("/overrides", json={"session_id": sid, "prn": student, "requested_status": "LATE",
                                          "late_minutes": 17, "reason": "Arrived after the group photo"},
                      headers=teacher_headers)
    assert res.status_code == 201
    row = attendance_row(sid, student)
    assert row["status"] == "LATE" and row["late_minutes"] == 17


def test_student_portal_scope(client, student, login, register) -> None:
    other, _ = register(unique_identity())
    headers = login(student, "StudentPass1")
    mine = client.get(f"/attendance/student/{student}", headers=headers)
    assert mine.status_code == 200 and mine.json()["summary"]["prn"] == student
    assert client.get(f"/attendance/student/{other}", headers=headers).status_code == 403
    assert client.get("/students", headers=headers).status_code == 403


def test_qr_fallback(client, teacher_headers, open_session, student, login) -> None:
    sid = open_session(minutes_ago=2)
    qr = client.get(f"/sessions/{sid}/qr", headers=teacher_headers)
    assert qr.status_code == 200 and qr.json()["qr_png"].startswith("data:image/png")
    headers = login(student, "StudentPass1")
    bad = client.post("/attendance/qr", json={"session_id": sid, "code": "000000" if qr.json()["code"] != "000000"
                                              else "111111"}, headers=headers)
    assert bad.status_code == 400 and bad.json()["code"] == "QR_INVALID"
    ok = client.post("/attendance/qr", json={"session_id": sid, "code": qr_code_for(sid)}, headers=headers)
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "PRESENT" and attendance_row(sid, student)["method"] == "QR"
    assert client.post("/attendance/qr", json={"session_id": sid, "code": qr_code_for(sid)},
                       headers=headers).status_code == 409


@pytest.mark.parametrize("fmt,magic", [("csv", b"\xef\xbb\xbf"), ("xlsx", b"PK"), ("pdf", b"%PDF")])
def test_exports(client, admin_headers, academic, student, fmt, magic) -> None:
    res = client.get("/reports/export", params={"type": fmt, "scope": "student", "prn": student},
                     headers=admin_headers)
    assert res.status_code == 200 and res.content.startswith(magic)
    res = client.get("/reports/export", params={"type": fmt, "scope": "course",
                                                "course_id": academic["courses"]["TST201"]}, headers=admin_headers)
    assert res.status_code == 200 and res.content.startswith(magic)
    assert "attachment" in res.headers["content-disposition"]


def test_analytics_endpoints(client, admin_headers) -> None:
    for path in ("/analytics/summary", "/analytics/daily-trend", "/analytics/course-wise", "/analytics/heatmap",
                 "/analytics/top-bottom", "/analytics/spoof-per-day", "/analytics/recognition-stats",
                 "/analytics/low-confidence", "/analytics/today", "/health", "/config/public",
                 "/admin/sagas", "/admin/audit"):
        res = client.get(path, headers=admin_headers)
        assert res.status_code == 200, (path, res.text)
    spoof = client.get("/analytics/spoof-per-day", headers=admin_headers).json()
    assert isinstance(spoof, list)


def test_login_lockout_after_failures(client, admin_headers) -> None:
    res = client.post("/teachers", json={"employee_code": "TST-LOCK", "full_name": "Lock Test",
                                         "email": "lock.test@example.org", "branch": "CS",
                                         "password": "LockPass123"}, headers=admin_headers)
    assert res.status_code == 201, res.text
    assert res.json()["username"] == "TST-LOCK"  # the code is the login, not the e-mail
    for _ in range(5):
        assert client.post("/auth/login", data={"username": "TST-LOCK",
                                                "password": "wrong-pass1"}).status_code == 401
    locked = client.post("/auth/login", data={"username": "TST-LOCK", "password": "LockPass123"})
    assert locked.status_code == 423 and locked.json()["code"] == "ACCOUNT_LOCKED"
