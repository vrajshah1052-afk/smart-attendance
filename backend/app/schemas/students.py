from __future__ import annotations

from typing import Any

from pydantic import BaseModel, EmailStr, Field, field_validator


class StudentBase(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    phone: str = Field(pattern=r"^\+?[0-9]{10,14}$")
    branch: str = Field(min_length=2, max_length=10)
    year: int = Field(ge=1, le=4)
    division: str = Field(min_length=1, max_length=2)
    roll_no: int = Field(ge=1, le=300)

    @field_validator("full_name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = " ".join(v.split())
        if not all(ch.isalpha() or ch in " .'-" for ch in v):
            raise ValueError("Name may only contain letters, spaces and . ' -")
        return v

    @field_validator("branch", "division")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("email")
    @classmethod
    def _lower(cls, v: str) -> str:
        return v.lower()

    @field_validator("phone", mode="before")
    @classmethod
    def _phone(cls, v: Any) -> Any:
        return str(v).replace(" ", "").replace("-", "") if v is not None else v


class StudentCreate(StudentBase):
    prn: str = Field(min_length=6, max_length=20)
    consent: bool
    password: str | None = Field(default=None, max_length=72)

    @field_validator("prn")
    @classmethod
    def _prn(cls, v: str) -> str:
        v = v.strip().upper()
        if not v.isalnum():
            raise ValueError("PRN must be alphanumeric")
        return v

    @field_validator("consent")
    @classmethod
    def _consent(cls, v: bool) -> bool:
        if not v:
            raise ValueError("Biometric consent is required to register a face profile")
        return v


class StudentUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=120)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, pattern=r"^\+?[0-9]{10,14}$")
    branch: str | None = None
    year: int | None = Field(default=None, ge=1, le=4)
    division: str | None = None
    roll_no: int | None = Field(default=None, ge=1, le=300)
    reason: str | None = Field(default=None, max_length=255)


class RejectRequest(BaseModel):
    reason: str = Field(min_length=5, max_length=500,
                        description="Why the sign-up is rejected (kept in the audit trail)")


class ForgetRequest(BaseModel):
    confirm_prn: str = Field(description="Type the PRN again to confirm irreversible erasure")
