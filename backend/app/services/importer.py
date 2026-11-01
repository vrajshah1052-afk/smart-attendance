"""Bulk student import from CSV (profiles only; faces are enrolled later)."""
from __future__ import annotations

import base64
import csv
import io
import logging
from typing import Any

from pydantic import ValidationError
from sqlalchemy.exc import DBAPIError

from app.core.deps import CurrentUser
from app.core.errors import bad_request, translate_db_error
from app.core.security import generate_temp_password, hash_password
from app.db.mysql import audit_context, transaction
from app.repositories import students as students_repo
from app.repositories import users as users_repo
from app.schemas.students import StudentCreate

logger = logging.getLogger(__name__)

REQUIRED = ["prn", "name", "email", "phone", "branch", "year", "division", "roll_no", "consent"]
TEMPLATE = ("prn,name,email,phone,branch,year,division,roll_no,consent\n"
            "12320001,Riya Sharma,riya.sharma@student.example.org,9876543210,CS,2,B,1,yes\n"
            "12320002,Arjun Mehta,arjun.mehta@student.example.org,9876543211,CS,2,B,2,yes\n")
MAX_ROWS = 2000


def _truthy(value: str) -> bool:
    return str(value).strip().lower() in ("1", "y", "yes", "true", "on")


def _insert_row(conn: Any, model: StudentCreate, division: dict[str, Any], password_hash: str,
                actor: CurrentUser) -> int:
    with audit_context(conn, actor.user_id, "bulk import"):
        students_repo.insert_student(conn, {
            "prn": model.prn, "full_name": model.full_name, "email": model.email, "phone": model.phone,
            "division_id": division["division_id"], "roll_no": model.roll_no, "face_status": "PENDING"})
        users_repo.create_user(conn, username=model.prn, password_hash=password_hash, role="STUDENT",
                               prn=model.prn, must_change=True)
        return students_repo.auto_enroll(conn, model.prn, division["branch_id"], model.year)


def import_csv(content: bytes, actor: CurrentUser, atomic: bool = False) -> dict[str, Any]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise bad_request("CSV must be UTF-8 encoded", "CSV_ENCODING") from exc
    reader = csv.DictReader(io.StringIO(text))
    headers = [h.strip().lower() for h in (reader.fieldnames or [])]
    missing = [h for h in REQUIRED if h not in headers]
    if missing:
        raise bad_request(f"Missing CSV columns: {', '.join(missing)}", "CSV_COLUMNS", {"expected": REQUIRED})
    rows = [{(k or "").strip().lower(): (v or "").strip() for k, v in r.items()} for r in reader]
    if not rows:
        raise bad_request("CSV has no data rows", "CSV_EMPTY")
    if len(rows) > MAX_ROWS:
        raise bad_request(f"At most {MAX_ROWS} rows per import", "CSV_TOO_LARGE")

    results: list[dict[str, Any]] = []
    valid: list[tuple[int, StudentCreate, dict[str, Any]]] = []
    seen_prn, seen_email = set(), set()
    with transaction() as conn:
        for line, raw in enumerate(rows, start=2):
            try:
                model = StudentCreate(prn=raw["prn"], full_name=raw["name"], email=raw["email"], phone=raw["phone"],
                                      branch=raw["branch"], year=int(raw["year"] or 0), division=raw["division"],
                                      roll_no=int(raw["roll_no"] or 0), consent=_truthy(raw["consent"]))
            except (ValidationError, ValueError) as exc:
                msg = "; ".join(e["msg"] for e in exc.errors()) if isinstance(exc, ValidationError) else str(exc)
                results.append({"line": line, "prn": raw.get("prn"), "status": "ERROR", "error": msg})
                continue
            error = None
            division = students_repo.find_division(conn, model.branch, model.year, model.division)
            if model.prn in seen_prn or students_repo.exists(conn, model.prn):
                error = "PRN already exists"
            elif model.email in seen_email or students_repo.email_taken(conn, model.email):
                error = "E-mail already exists"
            elif not division:
                error = f"Unknown division {model.branch}-{model.year}-{model.division}"
            elif students_repo.roll_taken(conn, division["division_id"], model.roll_no):
                error = "Roll number already taken in division"
            if error:
                results.append({"line": line, "prn": model.prn, "status": "ERROR", "error": error})
                continue
            seen_prn.add(model.prn)
            seen_email.add(model.email)
            valid.append((line, model, division))

    if atomic and any(r["status"] == "ERROR" for r in results):
        return {"mode": "atomic", "imported": 0, "failed": len(results), "rows": results, "credentials_csv": None,
                "message": "Nothing imported: fix the errors and upload again"}

    credentials: list[tuple[str, str, str]] = []

    def _prepare() -> list[tuple[int, StudentCreate, dict[str, Any], str, str]]:
        prepared = []
        for line, model, division in valid:
            password = generate_temp_password()
            prepared.append((line, model, division, password, hash_password(password, rounds=10)))
        return prepared

    prepared = _prepare()
    if atomic:
        with transaction() as conn:  # all rows or nothing
            for line, model, division, password, pw_hash in prepared:
                enrolled = _insert_row(conn, model, division, pw_hash, actor)
                results.append({"line": line, "prn": model.prn, "status": "IMPORTED", "courses": enrolled})
                credentials.append((model.prn, model.full_name, password))
    else:
        for line, model, division, password, pw_hash in prepared:
            try:
                with transaction() as conn:
                    enrolled = _insert_row(conn, model, division, pw_hash, actor)
                results.append({"line": line, "prn": model.prn, "status": "IMPORTED", "courses": enrolled})
                credentials.append((model.prn, model.full_name, password))
            except DBAPIError as exc:
                mapped = translate_db_error(exc)
                results.append({"line": line, "prn": model.prn, "status": "ERROR",
                                "error": mapped.message if mapped else "database error"})

    results.sort(key=lambda r: r["line"])
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["username (PRN)", "name", "temporary_password"])
    writer.writerows(credentials)
    imported = sum(1 for r in results if r["status"] == "IMPORTED")
    logger.info("CSV import by %s: %d imported, %d failed", actor.username, imported, len(results) - imported)
    return {
        "mode": "atomic" if atomic else "partial",
        "imported": imported,
        "failed": len(results) - imported,
        "rows": results,
        "credentials_csv": base64.b64encode(buf.getvalue().encode("utf-8")).decode("ascii") if credentials else None,
        "message": "Students must change the temporary password at first login; faces can be enrolled from the "
                   "Students page.",
    }
