"""Public self sign-up: a student creates their own account from the login page.

Nobody on staff is involved, so the account is created with face_status
PENDING_APPROVAL: the student row and the encrypted face templates exist, but
POST /auth/login refuses the account until an admin approves it under
Admin -> Pending approvals. After approval the student logs in and joins the
courses they want with a class code.
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import ValidationError

from app.config import get_settings
from app.core.deps import SELF_SIGNUP
from app.core.errors import AppError, conflict, forbidden
from app.db.mysql import transaction
from app.face.imageio import read_upload
from app.repositories import students as students_repo
from app.routers.students import validation_error
from app.schemas.students import StudentCreate
from app.services import registration

router = APIRouter(prefix="/signup", tags=["signup"])


def _enabled() -> None:
    if not get_settings().self_registration_enabled:
        raise forbidden("Signing up yourself is turned off - ask your teacher to register you",
                        "SELF_REGISTRATION_DISABLED")


@router.get("", summary="Public: what the sign-up form needs (branches, years, divisions, photo count)")
def signup_options() -> dict:
    s = get_settings()
    with transaction() as conn:
        rows = students_repo.academic_structure(conn)
    branches: dict[str, dict[str, Any]] = {}
    for r in rows:
        b = branches.setdefault(r["code"], {"code": r["code"], "name": r["name"], "years": {}})
        b["years"].setdefault(str(r["year_of_study"]), []).append(r["division"])
    return {
        "enabled": s.self_registration_enabled,
        "requires_approval": s.signup_requires_approval,
        "min_photos": s.min_reg_photos,
        "max_photos": s.max_reg_photos,
        "branches": [{"code": b["code"], "name": b["name"],
                      "years": {y: sorted(set(d)) for y, d in sorted(b["years"].items())}}
                     for b in branches.values()],
    }


@router.post("/quality-check", summary="Public: check one sign-up photo without saving it")
def signup_quality_check(photo: UploadFile = File(...)) -> dict:
    _enabled()
    result = registration.quality_check(read_upload(photo, get_settings().max_upload_bytes))
    if result["duplicate_of"]:  # an anonymous caller must not learn whose face it matched
        result["duplicate_of"] = {"registered": True}
    return result


@router.post("", status_code=201, summary="Public: a student signs up with 5-10 face photos (needs admin approval)")
def signup(
    full_name: Annotated[str, Form(alias="name")],
    prn: Annotated[str, Form()],
    email: Annotated[str, Form()],
    phone: Annotated[str, Form()],
    branch: Annotated[str, Form()],
    year: Annotated[int, Form()],
    division: Annotated[str, Form()],
    roll_no: Annotated[int, Form()],
    password: Annotated[str, Form()],
    consent: Annotated[bool, Form()] = False,
    photos: list[UploadFile] = File(..., description="5-10 photos: front, left, right"),
) -> dict:
    _enabled()
    s = get_settings()
    try:
        payload = StudentCreate(full_name=full_name, prn=prn, email=email, phone=phone, branch=branch, year=year,
                                division=division, roll_no=roll_no, consent=consent, password=password)
    except ValidationError as exc:
        raise validation_error(exc) from exc
    try:
        result = registration.register_student(
            payload, [read_upload(p, s.max_upload_bytes) for p in photos], SELF_SIGNUP,
            requires_approval=s.signup_requires_approval, auto_enroll=False)
    except AppError as exc:
        if exc.code == "DUPLICATE_FACE":  # no PRN of the matched student for an anonymous caller
            raise conflict("This face is already registered. Log in with your PRN instead", "DUPLICATE_FACE") from exc
        raise
    pending = bool(result.get("pending_approval"))
    return {
        "prn": payload.prn,
        "pending_approval": pending,
        "embeddings_stored": result["embeddings_stored"],
        "message": ("Account created. An admin has to approve you before you can log in - "
                    "you will then sign in with your PRN and join the courses you want."
                    if pending else "Account created. You can log in with your PRN now."),
    }
