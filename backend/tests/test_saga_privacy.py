"""Cross-database saga: compensation on MongoDB failure, delete, right to be forgotten."""
from __future__ import annotations

import hashlib

import pytest
from pymongo.errors import ServerSelectionTimeoutError
from sqlalchemy import text

from app.db.mongo import C, col
from app.db.mysql import fetch_all, fetch_one, fetch_scalar, transaction
from app.repositories import embeddings as emb_repo
from tests.conftest import new_prn
from tests.fakes import identity

pytestmark = pytest.mark.integration


def test_registration_rolls_back_mysql_when_mongo_fails(client, academic, register, monkeypatch) -> None:
    def boom(_docs):
        raise ServerSelectionTimeoutError("simulated MongoDB outage")

    monkeypatch.setattr(emb_repo, "insert_many", boom)
    prn = new_prn()
    _, body = register(identity(301), prn=prn, expect=503)
    assert body["code"] == "REGISTRATION_ROLLED_BACK"

    with transaction() as conn:
        assert fetch_scalar(conn, "SELECT COUNT(*) FROM students WHERE prn = :p", {"p": prn}) == 0
        assert fetch_scalar(conn, "SELECT COUNT(*) FROM users WHERE prn = :p", {"p": prn}) == 0
        saga = fetch_one(conn, "SELECT status, steps FROM saga_log WHERE subject = :p", {"p": prn})
    assert saga["status"] == "COMPENSATED"
    assert '"COMPENSATED"' in saga["steps"] and '"FAILED"' in saga["steps"]
    # compensation also left no audit trail of a half-registered student behind except the DELETE record
    with transaction() as conn:
        actions = [r["action"] for r in fetch_all(conn, "SELECT action FROM audit_log WHERE record_id = :p",
                                                   {"p": prn})]
    assert actions == ["DELETE"]


def test_forget_me_cascades_across_both_databases(client, academic, register, open_session, login) -> None:
    base = identity(302)
    prn, reg = register(base, password="ForgetMe123")
    sid = open_session()
    with transaction() as conn:
        conn.execute(text("""INSERT INTO attendance (session_id, prn, status, method) VALUES (:s, :p, 'PRESENT', 'QR')"""),
                     {"s": sid, "p": prn})
        conn.execute(text("SET @app_user_id = NULL, @audit_reason = 'test', @audit_action = NULL"))
        conn.execute(text("UPDATE attendance SET status = 'LATE', marked_at = NOW() WHERE session_id = :s AND prn = :p"),
                     {"s": sid, "p": prn})
    col(C.RECOGNITION_LOGS).insert_one({"kind": "GROUP", "status": "MATCHED", "prn": prn, "confidence": 0.8,
                                        "session_id": sid, "created_at": __import__("datetime").datetime.utcnow()})
    headers = login(prn, "ForgetMe123")

    bad = client.post(f"/students/{prn}/forget", json={"confirm_prn": "WRONG"}, headers=headers)
    assert bad.status_code == 400
    res = client.post(f"/students/{prn}/forget", json={"confirm_prn": prn}, headers=headers)
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["mode"] == "FORGET" and out["mongo"]["face_embeddings"] == 5

    digest = hashlib.sha256(prn.encode()).hexdigest()
    with transaction() as conn:
        for table in ("students", "users", "enrollments", "attendance"):
            assert fetch_scalar(conn, f"SELECT COUNT(*) FROM {table} WHERE prn = :p", {"p": prn}) == 0
        erase = fetch_one(conn, "SELECT * FROM audit_log WHERE action = 'ERASE' AND record_id = :h", {"h": digest})
        leaked = fetch_scalar(conn, "SELECT COUNT(*) FROM audit_log WHERE JSON_SEARCH(COALESCE(old_values, '{}'), "
                                    "'one', :p) IS NOT NULL OR JSON_SEARCH(COALESCE(new_values, '{}'), 'one', :p) "
                                    "IS NOT NULL OR record_id = :p", {"p": prn})
        saga = fetch_one(conn, "SELECT status FROM saga_log WHERE subject = :h", {"h": digest})
    assert erase is not None and leaked == 0
    assert saga["status"] == "COMPLETED"
    assert col(C.FACE_EMBEDDINGS).count_documents({"prn": prn}) == 0
    assert col(C.RECOGNITION_LOGS).count_documents({"prn": prn}) == 0
    # token still valid but the account is gone
    assert client.post("/auth/login", data={"username": prn, "password": "ForgetMe123"}).status_code == 401


def test_admin_delete_removes_profile_and_templates(client, academic, register, admin_headers, teacher_headers) -> None:
    prn, _ = register(identity(303))
    assert client.delete(f"/students/{prn}", headers=teacher_headers).status_code == 403  # admin only
    res = client.delete(f"/students/{prn}", params={"reason": "left the institute"}, headers=admin_headers)
    assert res.status_code == 200, res.text
    assert col(C.FACE_EMBEDDINGS).count_documents({"prn": prn}) == 0
    with transaction() as conn:
        row = fetch_one(conn, "SELECT reason FROM audit_log WHERE table_name = 'students' AND record_id = :p "
                              "AND action = 'DELETE'", {"p": prn})
    assert row["reason"] == "left the institute"


def test_delete_rolls_back_when_mysql_step_fails(client, academic, register, admin_headers, monkeypatch) -> None:
    from app.repositories import students as students_repo

    prn, _ = register(identity(304))

    def broken(_conn, _prn):
        raise RuntimeError("simulated MySQL failure")

    monkeypatch.setattr(students_repo, "delete_student", broken)
    res = client.delete(f"/students/{prn}", headers=admin_headers)
    assert res.status_code == 503 and res.json()["code"] == "DELETE_ROLLED_BACK"
    # compensation restored the soft-deleted templates
    assert col(C.FACE_EMBEDDINGS).count_documents({"prn": prn, "active": True}) == 5
