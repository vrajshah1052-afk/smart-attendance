from __future__ import annotations

from pydantic import BaseModel, Field


class UserOut(BaseModel):
    user_id: int
    username: str
    role: str
    full_name: str | None = None
    email: str | None = None
    prn: str | None = None
    teacher_id: int | None = None
    must_change_password: bool = False


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=72)
    new_password: str = Field(min_length=8, max_length=72)
