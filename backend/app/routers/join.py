"""Class codes: every course has a 6-character code and a QR poster.

A student scans the QR (or types the code) and lands on /join/<code>:
existing students log in and join the course, new students sign up there
with their face photos (REGISTER saga) and are enrolled straight away.
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, ValidationError

from app.config import get_settings
from app.core.deps import SELF_SIGNUP, STUDENT, CurrentUser, get_current_user, require_staff
from app.core.errors import AppError, conflict, forbidden, not_found
from app.db.mysql import transaction
from app.face.imageio import read_upload
from app.repositories import courses as courses_repo
from app.repositories import students as students_repo
from app.repositories import users as users_repo
from app.routers.auth import issue_token
from app.routers.students import validation_error
from app.schemas.students import StudentCreate
from app.services import registration
from app.services.challenges import qr_png
from app.services.notify import event

router = APIRouter(tags=["join"])


class JoinToggle(BaseModel):
    open: bool


def _course_out(course: dict[str, Any]) -> dict[str, Any]:
    return {k: course[k] for k in ("course_id", "code", "name", "credits", "branch", "branch_name", "year_of_study",
                                   "semester", "coordinator", "enrolled")}


def _poster(course: dict[str, Any]) -> dict[str, Any]:
    url = f"{get_settings().public_url}/join/{course['join_code']}"
    return {"course": _course_out(course), "join_code": course["join_code"], "join_open": bool(course["join_open"]),
            "url": url, "qr_png": qr_png(url, box_size=10)}


def _managed_course(conn: Any, course_id: int, user: CurrentUser) -> None:
    if not courses_repo.get_course(conn, course_id):
        raise not_found("Course not found", "COURSE_NOT_FOUND")
    if not user.is_admin and not courses_repo.is_coordinator(conn, course_id, user.teacher_id or -1):
        raise forbidden("Only the course coordinator or an admin can change the class code")


def _joinable(conn: Any, code: str) -> dict[str, Any]:
    course = courses_repo.get_by_join_code(conn, courses_repo.normalise_join_code(code))
    if not course:
        raise not_found("No class has this code. Check it, or ask your teacher for the current one",
                        "JOIN_CODE_INVALID")
    if not course["join_open"]:
        raise conflict(f"{course['code']} is not taking new students right now", "JOIN_CLOSED")
    return course


# ------------------------------------------------------------------ staff
@router.get("/courses/{course_id}/join", summary="Class code + QR poster students scan to join the course")
def course_join(course_id: int, _: CurrentUser = Depends(require_staff)) -> dict:
    with transaction() as conn:
        if not courses_repo.get_course(conn, course_id):
            raise not_found("Course not found", "COURSE_NOT_FOUND")
        courses_repo.ensure_join_code(conn, course_id)
        course = courses_repo.join_info(conn, course_id)
    return _poster(course or {})


@router.post("/courses/{course_id}/join/reset", summary="New class code (the old QR stops working)")
def reset_join_code(course_id: int, user: CurrentUser = Depends(require_staff)) -> dict:
    with transaction() as conn:
        _managed_course(conn, course_id, user)
        courses_repo.new_join_code(conn, course_id)
        course = courses_repo.join_info(conn, course_id)
    return _poster(course or {})


@router.put("/courses/{course_id}/join", summary="Open or close joining with the class code")
def toggle_join(course_id: int, body: JoinToggle, user: CurrentUser = Depends(require_staff)) -> dict:
    with transaction() as conn:
        _managed_course(conn, course_id, user)
        courses_repo.ensure_join_code(conn, course_id)
        courses_repo.set_join_open(conn, course_id, body.open)
        course = courses_repo.join_info(conn, course_id)
    return _poster(course or {})


# ------------------------------------------------------------------ public / students
@router.get("/join/{code}", summary="Public: the course behind a class code (what a scanned QR shows)")
def join_preview(code: str) -> dict:
    s = get_settings()
    with transaction() as conn:
        course = courses_repo.get_by_join_code(conn, courses_repo.normalise_join_code(code))
        if not course:
            raise not_found("No class has this code. Check it, or ask your teacher for the current one",
                            "JOIN_CODE_INVALID")
        divisions = students_repo.division_names(conn, course["branch_id"], course["year_of_study"])
    return {"course": _course_out(course), "join_code": course["join_code"], "join_open": bool(course["join_open"]),
            "divisions": divisions, "self_registration": s.self_registration_enabled,
            "min_photos": s.min_reg_photos, "max_photos": s.max_reg_photos}


@router.post("/join/{code}", summary="Student joins the course with its class code")
def join_course(code: str, user: CurrentUser = Depends(get_current_user)) -> dict:
    if user.role != STUDENT or not user.prn:
        raise forbidden("Only students join courses with a class code")
    with transaction() as conn:
        course = _joinable(conn, code)
        added = courses_repo.enroll(conn, course["course_id"], [user.prn])
        course = courses_repo.join_info(conn, course["course_id"]) or course
    if added:
        event("course_joined", {"course_id": course["course_id"], "course_code": course["code"], "prn": user.prn})
    return {"course": _course_out(course), "joined": bool(added), "already_enrolled": not added}


def _self_registration(conn: Any, code: str) -> dict[str, Any]:
    if not get_settings().self_registration_enabled:
        raise forbidden("Sign-up from a class code is turned off - ask your teacher to register you",
                        "SELF_REGISTRATION_DISABLED")
    return _joinable(conn, code)


@router.post("/join/{code}/quality-check", summary="Public: check one sign-up photo without saving it")
def join_quality_check(code: str, photo: UploadFile = File(...)) -> dict:
    with transaction() as conn:
        _self_registration(conn, code)
    result = registration.quality_check(read_upload(photo, get_settings().max_upload_bytes))
    if result["duplicate_of"]:  # an anonymous caller must not learn whose face it matched
        result["duplicate_of"] = {"registered": True}
    return result


@router.post("/join/{code}/register", status_code=201,
             summary="Public: a new student signs up with 5-10 face photos and joins the course")
def self_register(
    code: str,
    full_name: Annotated[str, Form(alias="name")],
    prn: Annotated[str, Form()],
    email: Annotated[str, Form()],
    phone: Annotated[str, Form()],
    division: Annotated[str, Form()],
    roll_no: Annotated[int, Form()],
    password: Annotated[str, Form()],
    consent: Annotated[bool, Form()] = False,
    photos: list[UploadFile] = File(..., description="5-10 photos: front, left, right"),
) -> dict:
    s = get_settings()
    with transaction() as conn:
        course = _self_registration(conn, code)
    try:
        payload = StudentCreate(full_name=full_name, prn=prn, email=email, phone=phone, branch=course["branch"],
                                year=course["year_of_study"], division=division, roll_no=roll_no, consent=consent,
                                password=password)
    except ValidationError as exc:
        raise validation_error(exc) from exc
    try:
        result = registration.register_student(payload, [read_upload(p, s.max_upload_bytes) for p in photos],
                                               SELF_SIGNUP, requires_approval=s.signup_requires_approval)
    except AppError as exc:
        if exc.code == "DUPLICATE_FACE":  # same as above: no PRN of the matched student
            raise conflict("This face is already registered. Log in with your PRN and join instead",
                           "DUPLICATE_FACE") from exc
        raise
    with transaction() as conn:
        courses_repo.enroll(conn, course["course_id"], [payload.prn])
        user = users_repo.get_by_username(conn, payload.prn)
        course = courses_repo.join_info(conn, course["course_id"]) or course
    event("course_joined", {"course_id": course["course_id"], "course_code": course["code"], "prn": payload.prn})
    out = {"course": _course_out(course), "embeddings_stored": result["embeddings_stored"],
           "courses_enrolled": result["courses_enrolled"], "prn": payload.prn,
           "pending_approval": bool(result.get("pending_approval"))}
    if out["pending_approval"]:
        # no token: the account cannot be used until an admin approves it
        out["message"] = ("You are signed up and enrolled in this class, but an admin has to approve "
                          "your account before you can log in.")
        return out
    return {**issue_token(user or {}).model_dump(), **out}
