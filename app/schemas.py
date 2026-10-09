from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.config import settings
from app.models import CertificateStatus, JobStatus


class RecipientIn(BaseModel):
    """A single recipient. Validated row by row (see services/validation.py),
    so one bad row doesn't reject the whole request."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100)
    email: EmailStr

    @field_validator("name")
    @classmethod
    def name_is_printable(cls, v: str) -> str:
        if not v.isprintable():
            raise ValueError("name contains control characters")
        # The template uses the PDF built-in fonts, which only cover Latin
        # characters (WinAnsi / cp1252). Better to reject than print boxes.
        try:
            v.encode("cp1252")
        except UnicodeEncodeError:
            raise ValueError("name contains characters the certificate font cannot display")
        return v


class JobCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    course_name: str = Field(min_length=1, max_length=200, examples=["Intro to Python"])
    issuer: str = Field(min_length=1, max_length=200, examples=["Acme Academy"])
    issue_date: date | None = Field(default=None, description="Defaults to today")
    # Kept loose on purpose: each item is validated individually against RecipientIn.
    recipients: list[Any] = Field(min_length=1)

    @field_validator("recipients")
    @classmethod
    def not_too_many(cls, v: list[Any]) -> list[Any]:
        if len(v) > settings.max_recipients_per_job:
            raise ValueError(f"at most {settings.max_recipients_per_job} recipients per job")
        return v


class RecipientError(BaseModel):
    index: int
    errors: list[str]


class Progress(BaseModel):
    total: int
    pending: int
    generated: int
    failed: int
    invalid: int
    percent_complete: float


class JobOut(BaseModel):
    id: str
    course_name: str
    issuer: str
    issue_date: date
    status: JobStatus
    error: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    progress: Progress


class JobCreated(BaseModel):
    job_id: str
    status: JobStatus
    total_recipients: int
    accepted: int
    rejected: int
    invalid_recipients: list[RecipientError]
    status_url: str
    certificates_url: str


class CertificateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    row_index: int
    recipient_name: str | None
    recipient_email: str | None
    status: CertificateStatus
    error: str | None
    verification_code: str | None
    generated_at: datetime | None
    download_url: str | None = None


class CertificatePage(BaseModel):
    job_id: str
    total: int
    limit: int
    offset: int
    items: list[CertificateOut]


class VerificationOut(BaseModel):
    valid: bool
    recipient_name: str
    course_name: str
    issuer: str
    issue_date: date
