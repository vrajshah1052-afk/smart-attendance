"""Students: registration (saga), photos, CRUD, delete / forget-me."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import ValidationError

from app.config import get_settings
from app.core.deps import CurrentUser, assert_student_scope, get_current_user, require_admin, require_staff
from app.core.errors import AppError, bad_request, conflict, forbidden, not_found
from app.db.mysql import audit_context, transaction
from app.face.imageio import read_upload
from app.repositories import embeddings as emb_repo
from app.repositories import students as students_repo
from app.schemas.students import ForgetRequest, RejectRequest, StudentCreate, StudentUpdate
from app.services import privacy, registration
from app.services.notify import event, notify

router = APIRouter(prefix="/students", tags=["students"])


def validation_error(exc: ValidationError) -> AppError:
    """422 in the app's error format for a model built from form fields."""
    return AppError(422, "VALIDATION_ERROR", "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}"
                                                       for e in exc.errors()),
                    [{"field": e["loc"][-1], "message": e["msg"]} for e in exc.errors()])


@router.post("/quality-check", summary="Check one enrolment photo (quality, pose, duplicate) without saving")
def quality_check(photo: UploadFile = File(...), prn: str | None = Form(None),
                  _: CurrentUser = Depends(require_staff)) -> dict:
    data = read_upload(photo, get_settings().max_upload_bytes)
    return registration.quality_check(data, exclude_prn=prn.upper() if prn else None)


@router.post("/register", status_code=201,
             summary="Register a student with 5-10 face photos (MySQL + MongoDB saga)")
def register(
    full_name: Annotated[str, Form(alias="name")],
    prn: Annotated[str, Form()],
    email: Annotated[str, Form()],
    phone: Annotated[str, Form()],
    branch: Annotated[str, Form()],
    year: Annotated[int, Form()],
    division: Annotated[str, Form()],
    roll_no: Annotated[int, Form()],
    consent: Annotated[bool, Form()] = False,
    password: Annotated[str | None, Form()] = None,
    photos: list[UploadFile] = File(..., description="5-10 photos: front, left, right, glasses / no glasses"),
    actor: CurrentUser = Depends(require_staff),
) -> dict:
    try:
        payload = StudentCreate(full_name=full_name, prn=prn, email=email, phone=phone, branch=branch, year=year,
                                division=division, roll_no=roll_no, consent=consent, password=password or None)
    except ValidationError as exc:
        raise validation_error(exc) from exc
    max_bytes = get_settings().max_upload_bytes
    return registration.register_student(payload, [read_upload(p, max_bytes) for p in photos], actor)


@router.get("", summary="List / search students")
def list_students(
    search: str | None = None, branch: str | None = None, year: int | None = Query(None, ge=1, le=4),
    division: str | None = None, face_status: str | None = None, course_id: int | None = None,
    limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0),
    _: CurrentUser = Depends(require_staff),
) -> dict:
    with transaction() as conn:
        rows, total = students_repo.list_students(
            conn, search=search, branch=branch.upper() if branch else None, year=year,
            division=division.upper() if division else None, face_status=face_status, course_id=course_id,
            limit=limit, offset=offset)
    try:
        counts = emb_repo.counts_by_prn([r["prn"] for r in rows])
    except Exception:  # noqa: BLE001 - Mongo down: list still works
        counts = {}
    for r in rows:
        r["face_templates"] = counts.get(r["prn"])
    return {"items": rows, "total": total, "limit": limit, "offset": offset}


@router.get("/pending", summary="Sign-ups waiting for admin approval")
def list_pending_approval(_: CurrentUser = Depends(require_admin)) -> dict:
    with transaction() as conn:
        rows = students_repo.list_pending_approval(conn)
    try:
        counts = emb_repo.counts_by_prn([r["prn"] for r in rows])
    except Exception:  # noqa: BLE001 - Mongo down: the list still works
        counts = {}
    for r in rows:
        r["face_templates"] = counts.get(r["prn"])
    return {"items": rows, "total": len(rows)}


def _pending_student(conn, prn: str) -> dict:
    student = students_repo.get_student(conn, prn)
    if not student:
        raise not_found("Student not found", "STUDENT_NOT_FOUND")
    if student["face_status"] != "PENDING_APPROVAL":
        raise bad_request(f"{prn} is not waiting for approval (face status {student['face_status']})",
                          "NOT_PENDING_APPROVAL")
    return student


@router.post("/{prn}/approve", summary="Approve a sign-up: the student can log in from now on")
def approve_student(prn: str, actor: CurrentUser = Depends(require_admin)) -> dict:
    prn = prn.upper()
    with transaction() as conn:
        with audit_context(conn, actor.user_id, "sign-up approved"):
            student = _pending_student(conn, prn)
            students_repo.set_face_status(conn, prn, "ENROLLED")
        student = students_repo.get_student(conn, prn)
    notify("SYSTEM", "Your account was approved",
           "You can now log in with your PRN and join your courses with a class code.", recipient_prn=prn)
    event("student_approved", {"prn": prn})
    return {"prn": prn, "face_status": "ENROLLED", "student": student}


@router.post("/{prn}/reject", summary="Reject a sign-up: the account and its face templates are erased")
def reject_student(prn: str, body: RejectRequest, actor: CurrentUser = Depends(require_admin)) -> dict:
    prn = prn.upper()
    with transaction() as conn:
        _pending_student(conn, prn)
    # DELETE saga across MySQL + MongoDB: the row, the login and the face templates all go,
    # and the reason stays in the audit trail
    result = privacy.remove_student(prn, actor, forget=False, reason=f"sign-up rejected: {body.reason}"[:255])
    event("student_rejected", {"prn": prn})
    return {"prn": prn, "rejected": True, "reason": body.reason, "saga_id": result.get("saga_id")}


@router.get("/me", summary="Own student profile")
def my_profile(user: CurrentUser = Depends(get_current_user)) -> dict:
    if not user.prn:
        raise forbidden("Only students have a student profile")
    return get_student(user.prn, user)


@router.get("/{prn}", summary="Student profile + face template metadata")
def get_student(prn: str, user: CurrentUser = Depends(get_current_user)) -> dict:
    prn = prn.upper()
    assert_student_scope(user, prn)
    with transaction() as conn:
        student = students_repo.get_student(conn, prn)
        if not student:
            raise not_found("Student not found", "STUDENT_NOT_FOUND")
        student["courses"] = students_repo.enrolled_courses(conn, prn)
    try:
        student["face_templates"] = [
            {k: v for k, v in t.items() if k in ("_id", "model", "pose", "yaw", "source", "active", "created_at")}
            for t in emb_repo.metadata_for_prn(prn)]
    except Exception:  # noqa: BLE001
        student["face_templates"] = None
    return student


@router.put("/{prn}", summary="Update student profile (audited)")
def update_student(prn: str, body: StudentUpdate, actor: CurrentUser = Depends(require_staff)) -> dict:
    prn = prn.upper()
    with transaction() as conn:
        current = students_repo.get_student(conn, prn)
        if not current:
            raise not_found("Student not found", "STUDENT_NOT_FOUND")
        fields = body.model_dump(exclude_none=True, exclude={"branch", "year", "division", "reason"})
        if any(v is not None for v in (body.branch, body.year, body.division)):
            division = students_repo.find_division(conn, (body.branch or current["branch"]).upper(),
                                                   body.year or current["year"],
                                                   (body.division or current["division"]).upper())
            if not division:
                raise bad_request("Unknown branch/year/division", "UNKNOWN_DIVISION")
            fields["division_id"] = division["division_id"]
        if "email" in fields:
            fields["email"] = fields["email"].lower()
            if students_repo.email_taken(conn, fields["email"], exclude_prn=prn):
                raise conflict("E-mail already used by another student", "EMAIL_EXISTS")
        roll = fields.get("roll_no", current["roll_no"])
        div_id = fields.get("division_id", current["division_id"])
        if ("roll_no" in fields or "division_id" in fields) and students_repo.roll_taken(conn, div_id, roll, prn):
            raise conflict("Roll number already taken in that division", "ROLL_EXISTS")
        with audit_context(conn, actor.user_id, body.reason or "profile update"):
            students_repo.update_student(conn, prn, fields)
        return students_repo.get_student(conn, prn) or {}


@router.post("/{prn}/photos", summary="Add photos / re-enrol a student's face")
def add_photos(prn: str, photos: list[UploadFile] = File(...), replace: bool = Form(False),
               actor: CurrentUser = Depends(require_staff)) -> dict:
    if replace and not actor.is_admin:
        raise forbidden("Only admins can replace all face templates")
    max_bytes = get_settings().max_upload_bytes
    return registration.add_photos(prn.upper(), [read_upload(p, max_bytes) for p in photos], replace, actor)


@router.delete("/{prn}", summary="Delete a student (DELETE saga across MySQL + MongoDB)")
def delete_student(prn: str, reason: str | None = Query(None, max_length=255),
                   actor: CurrentUser = Depends(require_admin)) -> dict:
    return privacy.remove_student(prn.upper(), actor, forget=False, reason=reason)


@router.post("/{prn}/forget", summary="Right to be forgotten: erase every trace (FORGET saga)")
def forget_student(prn: str, body: ForgetRequest, user: CurrentUser = Depends(get_current_user)) -> dict:
    prn = prn.upper()
    if not (user.is_admin or user.prn == prn):
        raise forbidden("Only the student or an admin can request erasure")
    if body.confirm_prn.strip().upper() != prn:
        raise bad_request("Confirmation PRN does not match", "CONFIRMATION_MISMATCH")
    return privacy.remove_student(prn, user, forget=True)
