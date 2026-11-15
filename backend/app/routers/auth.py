"""Authentication: JWT login, current user, password change."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm

from app.config import get_settings
from app.core.deps import CurrentUser, get_current_user
from app.core.errors import AppError
from app.core.security import (create_access_token, dummy_verify, hash_password, validate_password_strength,
                               verify_password)
from app.db.mysql import transaction
from app.repositories import students as students_repo
from app.repositories import users as users_repo
from app.schemas.auth import ChangePasswordRequest, TokenResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_out(row: dict) -> UserOut:
    return UserOut(user_id=row["user_id"], username=row["username"], role=row["role"], full_name=row["full_name"],
                   email=row["email"], prn=row["prn"], teacher_id=row["teacher_id"],
                   must_change_password=bool(row["must_change_password"]))


def _awaiting_approval(conn, user: dict) -> bool:
    """True for a student who signed up themselves and has not been approved yet."""
    if user["role"] != "STUDENT" or not user["prn"]:
        return False
    student = students_repo.get_student(conn, user["prn"])
    return bool(student and student["face_status"] == "PENDING_APPROVAL")


@router.post("/login", response_model=TokenResponse, summary="Login (e-mail for admins, employee code for teachers, PRN for students)")
def login(form: OAuth2PasswordRequestForm = Depends()) -> TokenResponse:
    s = get_settings()
    username = form.username.strip()
    username = username.lower() if "@" in username else username.upper()
    error: AppError | None = None
    with transaction() as conn:
        user = users_repo.get_by_username(conn, username)
        if user is None or not user["is_active"]:
            dummy_verify()
            error = AppError(401, "INVALID_CREDENTIALS", "Invalid username or password")
        elif user["is_locked"]:
            error = AppError(423, "ACCOUNT_LOCKED", f"Too many failed attempts. Try again in {s.login_lock_minutes} min")
        elif not user["password_hash"]:
            error = AppError(403, "ACCOUNT_NOT_ACTIVATED", "Account is not activated yet - contact your teacher")
        elif not verify_password(form.password, user["password_hash"]):
            users_repo.record_login_failure(conn, user["user_id"], s.login_max_failures, s.login_lock_minutes)
            error = AppError(401, "INVALID_CREDENTIALS", "Invalid username or password")
        elif _awaiting_approval(conn, user):
            # the password was right, so telling them the account is held gives nothing away
            error = AppError(403, "PENDING_APPROVAL",
                             "Your account is waiting for an admin to approve it. You can log in once approved.")
        else:
            users_repo.record_login_success(conn, user["user_id"])
    # raise only after COMMIT so the failed-attempt counter is persisted
    if error:
        raise error
    assert user is not None
    return issue_token(user)


def issue_token(user: dict) -> TokenResponse:
    """JWT for a users row as returned by users_repo.get_by_username / get_by_id."""
    token, expires = create_access_token(str(user["user_id"]), {
        "role": user["role"], "username": user["username"], "prn": user["prn"],
        "teacher_id": user["teacher_id"], "name": user["full_name"]})
    return TokenResponse(access_token=token, expires_in=expires, user=_user_out(user))


@router.get("/me", summary="Current user profile")
def me(user: CurrentUser = Depends(get_current_user)) -> dict:
    with transaction() as conn:
        row = users_repo.get_by_id(conn, user.user_id)
        if not row:
            raise AppError(401, "USER_GONE", "User no longer exists")
        out = _user_out(row).model_dump()
        if row["prn"]:
            out["student"] = students_repo.get_student(conn, row["prn"])
    return out


@router.post("/change-password", summary="Change own password")
def change_password(body: ChangePasswordRequest, user: CurrentUser = Depends(get_current_user)) -> dict:
    validate_password_strength(body.new_password)
    with transaction() as conn:
        row = users_repo.get_by_id(conn, user.user_id)
        if not row or not verify_password(body.current_password, row["password_hash"]):
            raise AppError(400, "WRONG_PASSWORD", "Current password is incorrect")
        if body.current_password == body.new_password:
            raise AppError(400, "SAME_PASSWORD", "New password must differ from the current one")
        users_repo.set_password(conn, user.user_id, hash_password(body.new_password), must_change=False)
    return {"ok": True}
