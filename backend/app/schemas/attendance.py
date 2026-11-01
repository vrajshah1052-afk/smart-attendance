from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ManualAddition(BaseModel):
    prn: str
    reason: str = Field(min_length=5, max_length=255)


class GroupConfirmRequest(BaseModel):
    draft_id: str
    session_id: int
    prns: list[str] = Field(default_factory=list, max_length=500,
                            description="Recognised students the teacher kept ticked")
    manual: list[ManualAddition] = Field(default_factory=list, max_length=500,
                                         description="Students added by hand (audited)")

    @field_validator("prns")
    @classmethod
    def _dedupe(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(p.strip().upper() for p in v))


class QRMarkRequest(BaseModel):
    session_id: int
    code: str = Field(pattern=r"^[0-9]{6}$")


class OverrideCreate(BaseModel):
    session_id: int
    prn: str
    requested_status: Literal["PRESENT", "LATE", "ABSENT"]
    reason: str = Field(min_length=5, max_length=500)
    late_minutes: int | None = Field(default=None, ge=0, le=600)
    apply_now: bool = Field(default=True, description="Staff only: approve immediately")


class Decision(BaseModel):
    note: str | None = Field(default=None, max_length=255)


class ReviewDecision(BaseModel):
    note: str | None = Field(default=None, max_length=255)
    prn: str | None = Field(default=None, description="Override the suggested student")
    add_to_profile: bool = Field(default=False, description="Store this face as an extra template")
