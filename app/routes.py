import os
import re
import tempfile
import zipfile
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.database import get_db
from app.dependencies import get_runner, get_storage_dir
from app.models import Certificate, CertificateStatus, Job
from app.schemas import (
    CertificateOut,
    CertificatePage,
    JobCreate,
    JobCreated,
    JobOut,
    RecipientError,
    VerificationOut,
)
from app.services import jobs as job_service
from app.services.csv_import import CSVError, parse_recipients_csv
from app.services.validation import format_errors

router = APIRouter(prefix="/api/v1")

MAX_CSV_BYTES = 2 * 1024 * 1024


def _get_job_or_404(db: Session, job_id: str) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return job


def _job_out(db: Session, job: Job) -> JobOut:
    return JobOut(
        id=job.id,
        course_name=job.course_name,
        issuer=job.issuer,
        issue_date=job.issue_date,
        status=job.status,
        error=job.error,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        progress=job_service.get_progress(db, job.id),
    )


def _cert_out(request: Request, cert: Certificate) -> CertificateOut:
    out = CertificateOut.model_validate(cert)
    if cert.status == CertificateStatus.GENERATED:
        out.download_url = request.app.url_path_for("download_certificate", certificate_id=cert.id)
    return out


def _safe_filename(name: str | None) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", name or "").strip("_")
    return slug or "certificate"


def _submit_job(payload: JobCreate, request: Request, db: Session, runner) -> JobCreated:
    try:
        job, invalid = job_service.create_job(db, payload)
    except job_service.NoValidRecipients as exc:
        raise HTTPException(
            422,
            detail={
                "message": "none of the recipients are valid",
                "invalid_recipients": [{"index": r.index, "errors": r.errors} for r in exc.invalid],
            },
        )

    runner.submit(job.id)

    total = len(payload.recipients)
    return JobCreated(
        job_id=job.id,
        status=job.status,
        total_recipients=total,
        accepted=total - len(invalid),
        rejected=len(invalid),
        invalid_recipients=[RecipientError(index=r.index, errors=r.errors) for r in invalid],
        status_url=request.app.url_path_for("get_job", job_id=job.id),
        certificates_url=request.app.url_path_for("list_job_certificates", job_id=job.id),
    )


@router.post("/jobs", status_code=202, response_model=JobCreated, tags=["jobs"])
def create_generation_job(
    payload: JobCreate,
    request: Request,
    db: Session = Depends(get_db),
    runner=Depends(get_runner),
):
    """Submit a bulk generation request. Returns immediately (202) with a job id;
    certificates are generated in the background.

    Invalid recipients don't reject the request - they're reported back and
    recorded on the job as `invalid`. Only if *every* recipient is invalid is
    the request rejected with 422.
    """
    return _submit_job(payload, request, db, runner)


@router.post("/jobs/csv", status_code=202, response_model=JobCreated, tags=["jobs"])
def create_generation_job_from_csv(
    request: Request,
    file: UploadFile = File(..., description="CSV with `name` and `email` columns"),
    course_name: str = Form(...),
    issuer: str = Form(...),
    issue_date: date | None = Form(None),
    db: Session = Depends(get_db),
    runner=Depends(get_runner),
):
    """Same as `POST /jobs`, but recipients come from an uploaded CSV file.

    `index` in `invalid_recipients` is the data row number, starting at 0 for
    the first row under the header.
    """
    raw = file.file.read(MAX_CSV_BYTES + 1)
    if len(raw) > MAX_CSV_BYTES:
        raise HTTPException(413, f"CSV file is larger than {MAX_CSV_BYTES // (1024 * 1024)} MB")

    try:
        recipients = parse_recipients_csv(raw)
    except CSVError as exc:
        raise HTTPException(422, str(exc))

    try:
        payload = JobCreate(course_name=course_name, issuer=issuer, issue_date=issue_date, recipients=recipients)
    except ValidationError as exc:
        raise HTTPException(422, format_errors(exc))

    return _submit_job(payload, request, db, runner)


@router.get("/jobs", response_model=list[JobOut], tags=["jobs"])
def list_jobs(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    rows = db.scalars(select(Job).order_by(Job.created_at.desc()).limit(limit).offset(offset)).all()
    return [_job_out(db, job) for job in rows]


@router.get("/jobs/{job_id}", response_model=JobOut, tags=["jobs"])
def get_job(job_id: str, db: Session = Depends(get_db)):
    """Job status and progress counts."""
    return _job_out(db, _get_job_or_404(db, job_id))


@router.get("/jobs/{job_id}/certificates", response_model=CertificatePage, tags=["jobs"])
def list_job_certificates(
    job_id: str,
    request: Request,
    status: CertificateStatus | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Per-recipient results. Filter with `?status=failed` / `?status=invalid`
    to see exactly which recipients didn't get a certificate and why."""
    _get_job_or_404(db, job_id)

    query = select(Certificate).where(Certificate.job_id == job_id)
    if status is not None:
        query = query.where(Certificate.status == status)

    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(Certificate.row_index).limit(limit).offset(offset)).all()
    return CertificatePage(
        job_id=job_id,
        total=total,
        limit=limit,
        offset=offset,
        items=[_cert_out(request, c) for c in rows],
    )


@router.get("/jobs/{job_id}/certificates/archive", tags=["jobs"], response_class=FileResponse)
def download_job_archive(
    job_id: str,
    db: Session = Depends(get_db),
    storage_dir: Path = Depends(get_storage_dir),
):
    """All generated certificates of a job as a single ZIP."""
    _get_job_or_404(db, job_id)
    generated = db.scalars(
        select(Certificate)
        .where(Certificate.job_id == job_id, Certificate.status == CertificateStatus.GENERATED)
        .order_by(Certificate.row_index)
    ).all()
    if not generated:
        raise HTTPException(409, "no certificates have been generated for this job yet")

    fd, tmp_path = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for cert in generated:
            src = storage_dir / cert.file_path
            if src.exists():
                zf.write(src, arcname=f"{cert.row_index + 1:04d}_{_safe_filename(cert.recipient_name)}.pdf")

    return FileResponse(
        tmp_path,
        media_type="application/zip",
        filename=f"certificates_{job_id}.zip",
        background=BackgroundTask(os.remove, tmp_path),
    )


@router.post("/jobs/{job_id}/retry", status_code=202, response_model=JobOut, tags=["jobs"])
def retry_job(
    job_id: str,
    db: Session = Depends(get_db),
    runner=Depends(get_runner),
):
    """Re-run generation for certificates that failed (not for invalid input)."""
    job = _get_job_or_404(db, job_id)
    try:
        job_service.retry_failed(db, job)
    except job_service.JobConflict as exc:
        raise HTTPException(409, str(exc))

    out = _job_out(db, job)
    runner.submit(job.id)
    return out


@router.get("/certificates/{certificate_id}", response_model=CertificateOut, tags=["certificates"])
def get_certificate(certificate_id: str, request: Request, db: Session = Depends(get_db)):
    cert = db.get(Certificate, certificate_id)
    if cert is None:
        raise HTTPException(404, "certificate not found")
    return _cert_out(request, cert)


@router.get("/certificates/{certificate_id}/download", tags=["certificates"], response_class=FileResponse)
def download_certificate(
    certificate_id: str,
    db: Session = Depends(get_db),
    storage_dir: Path = Depends(get_storage_dir),
):
    cert = db.get(Certificate, certificate_id)
    if cert is None:
        raise HTTPException(404, "certificate not found")
    if cert.status != CertificateStatus.GENERATED:
        raise HTTPException(409, f"certificate is not available (status: {cert.status.value})")

    path = storage_dir / cert.file_path
    if not path.exists():
        raise HTTPException(410, "certificate file is missing from storage")

    return FileResponse(
        path,
        media_type="application/pdf",
        filename=f"certificate_{_safe_filename(cert.recipient_name)}.pdf",
    )


@router.get("/verify/{code}", response_model=VerificationOut, tags=["certificates"])
def verify_certificate(code: str, db: Session = Depends(get_db)):
    """Check that a certificate ID printed on a PDF is genuine."""
    cert = db.scalar(
        select(Certificate).where(
            Certificate.verification_code == code.strip().upper(),
            Certificate.status == CertificateStatus.GENERATED,
        )
    )
    if cert is None:
        raise HTTPException(404, "no certificate with this ID")
    return VerificationOut(
        valid=True,
        recipient_name=cert.recipient_name,
        course_name=cert.job.course_name,
        issuer=cert.job.issuer,
        issue_date=cert.job.issue_date,
    )
