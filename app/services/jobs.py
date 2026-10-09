import logging
import secrets
from datetime import date
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import Certificate, CertificateStatus, Job, JobStatus, utcnow
from app.schemas import JobCreate, Progress
from app.services.pdf import CertificateData, render_certificate
from app.services.validation import InvalidRow, validate_recipients

logger = logging.getLogger(__name__)

UNFINISHED = (JobStatus.PENDING, JobStatus.PROCESSING)


class NoValidRecipients(Exception):
    def __init__(self, invalid: list[InvalidRow]):
        super().__init__("none of the recipients are valid")
        self.invalid = invalid


class JobConflict(Exception):
    pass


def new_verification_code() -> str:
    return secrets.token_hex(6).upper()


def create_job(db: Session, payload: JobCreate) -> tuple[Job, list[InvalidRow]]:
    valid, invalid = validate_recipients(payload.recipients)
    if not valid:
        raise NoValidRecipients(invalid)

    job = Job(
        course_name=payload.course_name,
        issuer=payload.issuer,
        issue_date=payload.issue_date or date.today(),
        status=JobStatus.PENDING,
    )
    for index, recipient in valid:
        job.certificates.append(
            Certificate(
                row_index=index,
                recipient_name=recipient.name,
                recipient_email=recipient.email,
                status=CertificateStatus.PENDING,
                verification_code=new_verification_code(),
            )
        )
    # invalid rows are stored too, so the job status shows the full picture
    for row in invalid:
        job.certificates.append(
            Certificate(
                row_index=row.index,
                recipient_name=row.name,
                recipient_email=row.email,
                status=CertificateStatus.INVALID,
                error="; ".join(row.errors),
            )
        )

    db.add(job)
    db.commit()
    return job, invalid


def get_progress(db: Session, job_id: str) -> Progress:
    rows = db.execute(
        select(Certificate.status, func.count())
        .where(Certificate.job_id == job_id)
        .group_by(Certificate.status)
    ).all()
    counts = {status: 0 for status in CertificateStatus}
    counts.update({status: n for status, n in rows})

    total = sum(counts.values())
    done = total - counts[CertificateStatus.PENDING]
    return Progress(
        total=total,
        pending=counts[CertificateStatus.PENDING],
        generated=counts[CertificateStatus.GENERATED],
        failed=counts[CertificateStatus.FAILED],
        invalid=counts[CertificateStatus.INVALID],
        percent_complete=round(100 * done / total, 1) if total else 100.0,
    )


def _generate_one(job: Job, cert: Certificate, storage_dir: Path) -> None:
    relative = Path(job.id) / f"{cert.id}.pdf"
    data = CertificateData(
        recipient_name=cert.recipient_name,
        course_name=job.course_name,
        issuer=job.issuer,
        issue_date=job.issue_date,
        verification_code=cert.verification_code,
    )
    try:
        render_certificate(data, storage_dir / relative)
    except Exception as exc:
        # one bad certificate shouldn't take the rest of the job down with it
        logger.warning("certificate %s (job %s) failed: %s", cert.id, job.id, exc)
        cert.status = CertificateStatus.FAILED
        cert.error = f"{type(exc).__name__}: {exc}"[:1000]
        return

    cert.status = CertificateStatus.GENERATED
    cert.file_path = relative.as_posix()
    cert.generated_at = utcnow()
    cert.error = None


def _final_status(progress: Progress) -> JobStatus:
    if progress.generated == 0:
        return JobStatus.FAILED
    if progress.failed or progress.invalid:
        return JobStatus.COMPLETED_WITH_ERRORS
    return JobStatus.COMPLETED


def process_job(job_id: str, session_factory: sessionmaker, storage_dir: Path) -> None:
    """Generate every pending certificate in a job.

    Only touches certificates still in PENDING, so it's safe to call again on a
    job that was interrupted (server restart) or after a retry.
    """
    db = session_factory()
    try:
        job = db.get(Job, job_id)
        if job is None:
            logger.warning("job %s not found, skipping", job_id)
            return

        job.status = JobStatus.PROCESSING
        job.started_at = job.started_at or utcnow()
        job.error = None
        db.commit()

        pending = db.scalars(
            select(Certificate)
            .where(Certificate.job_id == job_id, Certificate.status == CertificateStatus.PENDING)
            .order_by(Certificate.row_index)
        ).all()
        logger.info("job %s: generating %d certificates", job_id, len(pending))

        for cert in pending:
            _generate_one(job, cert, storage_dir)
            # commit per certificate so progress is visible while the job runs
            db.commit()

        progress = get_progress(db, job_id)
        job.status = _final_status(progress)
        if job.status == JobStatus.FAILED:
            job.error = "no certificates could be generated"
        job.completed_at = utcnow()
        db.commit()
        logger.info("job %s finished: %s", job_id, job.status.value)
    except Exception as exc:
        logger.exception("job %s crashed", job_id)
        db.rollback()
        job = db.get(Job, job_id)
        if job is not None:
            job.status = JobStatus.FAILED
            job.error = f"{type(exc).__name__}: {exc}"[:1000]
            job.completed_at = utcnow()
            db.commit()
    finally:
        db.close()


def retry_failed(db: Session, job: Job) -> int:
    """Put FAILED certificates back to PENDING. INVALID ones are not retried -
    the input itself is wrong, so they'd fail the same way again."""
    if job.status in UNFINISHED:
        raise JobConflict("job is still running")

    failed = db.scalars(
        select(Certificate).where(Certificate.job_id == job.id, Certificate.status == CertificateStatus.FAILED)
    ).all()
    if not failed:
        raise JobConflict("job has no failed certificates to retry")

    for cert in failed:
        cert.status = CertificateStatus.PENDING
        cert.error = None
    job.status = JobStatus.PENDING
    job.error = None
    job.completed_at = None
    db.commit()
    return len(failed)


def unfinished_job_ids(db: Session) -> list[str]:
    return list(db.scalars(select(Job.id).where(Job.status.in_(UNFINISHED)).order_by(Job.created_at)))
