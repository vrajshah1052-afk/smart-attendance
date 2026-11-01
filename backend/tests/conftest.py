"""pytest fixtures.

Integration tests run against the dedicated *test* schemas created by the
init scripts (MySQL `attendance_test`, MongoDB `attendance_logs_test`) and are
skipped automatically when the databases are unreachable.

    docker compose run --rm backend pytest -q
"""
from __future__ import annotations

import datetime as dt
import itertools
import os
import tempfile
from typing import Any, Iterator

import pytest

# ---- configure the app BEFORE it is imported -------------------------------
os.environ["TESTING"] = "true"
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["MYSQL_DATABASE"] = os.environ.get("TEST_MYSQL_DATABASE", "attendance_test")
os.environ["MONGO_DB"] = os.environ.get("TEST_MONGO_DB", "attendance_logs_test")
os.environ["MYSQL_CONNECT_RETRIES"] = "1"
os.environ["MATCH_THRESHOLD"] = "0.45"
os.environ["DUPLICATE_THRESHOLD"] = "0.60"
os.environ["LIVENESS_REQUIRED"] = "true"
os.environ["EMAIL_ENABLED"] = "false"
os.environ["SESSION_WINDOW_ENFORCED"] = "false"
os.environ["BCRYPT_ROUNDS"] = "4"
os.environ["ADMIN_EMAIL"] = "pytest-admin@example.org"
os.environ["ADMIN_PASSWORD"] = "PytestAdmin1"
os.environ["DEMO_USER_PASSWORD"] = ""
os.environ["AUTO_REENROLL"] = "true"
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="sfa-test-"))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import exc as sa_exc  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.mongo import get_db, ping_mongo  # noqa: E402
from app.db.mysql import fetch_one, fetch_scalar, get_engine, ping, transaction  # noqa: E402
from app.services import face_service  # noqa: E402
from tests.fakes import FakeEngine, PhotoFactory  # noqa: E402

TEACHER_EMAIL = "teacher.pytest@example.org"
TEACHER_PASSWORD = "TeacherPass1"
MYSQL_TABLES = ["attendance", "override_requests", "enrollments", "sessions", "users", "courses", "students",
                "teachers", "divisions", "branches", "audit_log", "saga_log"]

_prn_counter = itertools.count(1)


def new_prn(prefix: str = "TST") -> str:
    return f"{prefix}{os.getpid() % 1000:03d}{next(_prn_counter):05d}"


@pytest.fixture(scope="session")
def fake_engine() -> FakeEngine:
    engine = FakeEngine()
    face_service.set_engine(engine)
    return engine


@pytest.fixture(scope="session")
def photos(fake_engine: FakeEngine) -> PhotoFactory:
    return PhotoFactory(fake_engine)


@pytest.fixture(scope="session")
def require_db() -> None:
    if not (ping() and ping_mongo()):
        pytest.skip("MySQL/MongoDB test databases are not reachable")
    settings = get_settings()
    if not settings.mysql_database.endswith("_test") or not settings.mongo_db.endswith("_test"):
        pytest.exit("Refusing to wipe a non-test database", returncode=2)


def _wipe_databases() -> None:
    with get_engine().begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        for table in MYSQL_TABLES:
            conn.execute(text(f"TRUNCATE TABLE {table}"))
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
    db = get_db()
    for name in db.list_collection_names():
        db.drop_collection(name)


def _seed_academic() -> dict[str, Any]:
    with transaction() as conn:
        conn.execute(text("INSERT INTO branches (code, name) VALUES ('CS', 'Computer Engineering')"))
        branch = fetch_scalar(conn, "SELECT branch_id FROM branches WHERE code = 'CS'")
        conn.execute(text("""INSERT INTO divisions (branch_id, year_of_study, name)
                             VALUES (:b, 2, 'A'), (:b, 2, 'B'), (:b, 3, 'A')"""), {"b": branch})
        conn.execute(text("""INSERT INTO teachers (employee_code, full_name, email, branch_id)
                             VALUES ('TST-T1', 'Test Teacher', :e, :b)"""), {"e": TEACHER_EMAIL, "b": branch})
        teacher = fetch_scalar(conn, "SELECT teacher_id FROM teachers WHERE employee_code = 'TST-T1'")
        conn.execute(text("""INSERT INTO users (username, password_hash, role, teacher_id)
                             VALUES (:u, :h, 'TEACHER', :t)"""),
                     {"u": TEACHER_EMAIL, "h": hash_password(TEACHER_PASSWORD), "t": teacher})
        conn.execute(text("""INSERT INTO courses (code, name, credits, branch_id, year_of_study, semester, teacher_id)
                             VALUES ('TST201', 'Test DBMS', 4, :b, 2, 4, :t),
                                    ('TST202', 'Test OS', 3, :b, 2, 4, :t),
                                    ('TST301', 'Test Compilers', 3, :b, 3, 5, :t)"""), {"b": branch, "t": teacher})
        courses = {r[0]: r[1] for r in conn.execute(text("SELECT code, course_id FROM courses"))}
    return {"branch_id": branch, "teacher_id": teacher, "courses": courses}


@pytest.fixture(scope="session")
def client(require_db: None, fake_engine: FakeEngine) -> Iterator[TestClient]:
    _wipe_databases()
    with TestClient(__import__("app.main", fromlist=["app"]).app) as test_client:
        face_service.set_engine(fake_engine)
        yield test_client


@pytest.fixture(scope="session")
def academic(client: TestClient) -> dict[str, Any]:
    return _seed_academic()


def _login(client: TestClient, username: str, password: str) -> dict[str, str]:
    res = client.post("/auth/login", data={"username": username, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture(scope="session")
def admin_headers(client: TestClient) -> dict[str, str]:
    return _login(client, "pytest-admin@example.org", "PytestAdmin1")


@pytest.fixture(scope="session")
def teacher_headers(client: TestClient, academic: dict[str, Any]) -> dict[str, str]:
    return _login(client, TEACHER_EMAIL, TEACHER_PASSWORD)


@pytest.fixture()
def login(client: TestClient):
    return lambda username, password: _login(client, username, password)


@pytest.fixture()
def open_session(academic: dict[str, Any]):
    """Factory: an OPEN session of a course that started `minutes_ago` minutes ago."""

    def _make(course_code: str = "TST201", minutes_ago: int = 0, late_after: int = 10,
              status: str = "OPEN") -> int:
        with transaction() as conn:
            now = fetch_scalar(conn, "SELECT NOW()")
        for shift in range(0, 600):  # (course, date, start_time) is UNIQUE: find a free second
            start = (now - dt.timedelta(minutes=minutes_ago, seconds=shift)).replace(microsecond=0)
            if start.hour == 23 and start.minute >= 57:
                start = start.replace(minute=56)
            end = min(start + dt.timedelta(hours=2), dt.datetime.combine(start.date(), dt.time(23, 59, 59)))
            try:
                with transaction() as conn:
                    result = conn.execute(text("""
                        INSERT INTO sessions (course_id, teacher_id, session_date, start_time, end_time,
                                              late_after_min, status, opened_at)
                        VALUES (:c, :t, :d, :s, :e, :l, :st, IF(:st = 'OPEN', NOW(), NULL))"""),
                                          {"c": academic["courses"][course_code], "t": academic["teacher_id"],
                                           "d": start.date(), "s": start.time(), "e": end.time(), "l": late_after,
                                           "st": status})
                    return int(result.lastrowid)
            except sa_exc.IntegrityError:
                continue
        raise RuntimeError("could not allocate a session slot")

    return _make


@pytest.fixture()
def register(client: TestClient, admin_headers: dict[str, str], photos: PhotoFactory):
    """Factory: register a student (default year 2 div A) and return (prn, response json)."""

    def _register(base, prn: str | None = None, year: int = 2, division: str = "A",
                  expect: int = 201, photos_list: list[bytes] | None = None, **overrides: Any):
        prn = prn or new_prn()
        roll = int(prn[-4:]) % 300 or 1
        form = {"name": overrides.pop("name", "Test Student"), "prn": prn,
                "email": overrides.pop("email", f"{prn.lower()}@student.example.org"),
                "phone": "9876500000", "branch": "CS", "year": str(year), "division": division,
                "roll_no": str(overrides.pop("roll_no", roll)), "consent": overrides.pop("consent", "true")}
        form.update({k: str(v) for k, v in overrides.items()})
        files = [("photos", (f"p{i}.png", data, "image/png"))
                 for i, data in enumerate(photos_list if photos_list is not None else photos.enrolment_set(base))]
        res = client.post("/students/register", data=form, files=files, headers=admin_headers)
        assert res.status_code == expect, res.text
        return prn, res.json()

    return _register


def attendance_row(session_id: int, prn: str) -> dict[str, Any] | None:
    with transaction() as conn:
        return fetch_one(conn, "SELECT * FROM attendance WHERE session_id = :s AND prn = :p",
                         {"s": session_id, "p": prn})


def challenge(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    res = client.get("/liveness/challenge", headers=headers)
    assert res.status_code == 200, res.text
    return res.json()
