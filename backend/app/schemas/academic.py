from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, EmailStr, Field, model_validator

from app.core.utils import hour_slot


class SessionCreate(BaseModel):
    """A lecture is exactly one clock hour: 07:00-08:00, 08:00-09:00, ..."""

    course_id: int
    session_date: dt.date
    start_time: dt.time
    end_time: dt.time
    late_after_min: int = Field(default=10, ge=0, le=60)
    room: str | None = Field(default=None, max_length=20)
    topic: str | None = Field(default=None, max_length=200)
    teacher_id: int | None = None
    open_now: bool = False

    @model_validator(mode="after")
    def _one_hour_slot(self) -> "SessionCreate":
        if self.start_time.minute or self.start_time.second:
            raise ValueError("A lecture starts on the hour, for example 09:00")
        expected = hour_slot(self.start_time)[1]
        if self.end_time.replace(second=0) != expected.replace(second=0):
            raise ValueError(f"A lecture lasts one hour, so {self.start_time:%H:%M} ends at {expected:%H:%M}")
        return self

    @model_validator(mode="after")
    def _times(self) -> "SessionCreate":
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class SessionOpen(BaseModel):
    force: bool = False


class CourseCreate(BaseModel):
    code: str = Field(min_length=2, max_length=15)
    name: str = Field(min_length=3, max_length=150)
    credits: int = Field(default=3, ge=1, le=6)
    branch: str
    year_of_study: int = Field(ge=1, le=4)
    semester: int = Field(ge=1, le=8)
    teacher_id: int | None = None

    @model_validator(mode="after")
    def _semester(self) -> "CourseCreate":
        if self.semester not in (self.year_of_study * 2 - 1, self.year_of_study * 2):
            raise ValueError("semester must belong to the year of study")
        return self


class EnrollRequest(BaseModel):
    prns: list[str] = Field(min_length=1, max_length=500)


class TeacherPassword(BaseModel):
    password: str | None = Field(default=None, max_length=72,
                                 description="Leave out to generate a one-time password")


class SessionNow(BaseModel):
    """Start a lecture in the clock hour we are in right now."""

    course_id: int
    late_after_min: int = Field(default=10, ge=0, le=60)
    room: str | None = Field(default=None, max_length=20)
    topic: str | None = Field(default=None, max_length=200)
    teacher_id: int | None = None


class TeacherCreate(BaseModel):
    employee_code: str = Field(min_length=3, max_length=20)
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    phone: str | None = Field(default=None, pattern=r"^\+?[0-9]{10,14}$")
    branch: str
    designation: str = "Assistant Professor"
    password: str | None = Field(default=None, max_length=72)
