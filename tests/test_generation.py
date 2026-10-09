"""The PDF template and the job processor."""

from datetime import date

from app.models import Certificate, CertificateStatus, Job, JobStatus
from app.schemas import JobCreate
from app.services import jobs
from app.services.pdf import PAGE_W, CertificateData, _fit_font_size, render_certificate


def _data(**overrides):
    values = dict(
        recipient_name="Alice Johnson",
        course_name="Backend Development with FastAPI",
        issuer="Acme Academy",
        issue_date=date(2026, 10, 1),
        verification_code="ABC123DEF456",
    )
    values.update(overrides)
    return CertificateData(**values)


def test_render_certificate_writes_a_pdf(tmp_path):
    out = render_certificate(_data(), tmp_path / "nested" / "cert.pdf")

    content = out.read_bytes()
    assert content.startswith(b"%PDF-")
    assert b"Certificate - Alice Johnson" in content  # document title metadata
    assert not (tmp_path / "nested" / "cert.pdf.tmp").exists()


def test_long_names_shrink_to_fit():
    long_name = "Maximiliana Alexandrina Konstantinopoulou-Vanderbilt the Third"
    size = _fit_font_size(long_name, "Times-BoldItalic", 40, PAGE_W - 200)
    assert 12 <= size < 40


def test_render_handles_accented_names(tmp_path):
    out = render_certificate(_data(recipient_name="José Müller-Øster"), tmp_path / "cert.pdf")
    assert out.stat().st_size > 0


def test_process_job_generates_a_file_per_recipient(session_factory, storage_dir, payload):
    with session_factory() as db:
        job, _ = jobs.create_job(db, JobCreate(**payload()))

    jobs.process_job(job.id, session_factory, storage_dir)

    with session_factory() as db:
        job = db.get(Job, job.id)
        assert job.status == JobStatus.COMPLETED
        for cert in job.certificates:
            assert cert.status == CertificateStatus.GENERATED
            assert cert.verification_code
            path = storage_dir / cert.file_path
            assert path.exists()
            assert path.read_bytes().startswith(b"%PDF-")


def test_process_job_only_picks_up_pending_certificates(session_factory, storage_dir, payload, monkeypatch):
    """Simulates resuming a job that was interrupted half way."""
    with session_factory() as db:
        job, _ = jobs.create_job(db, JobCreate(**payload()))
        first = db.query(Certificate).filter_by(job_id=job.id, row_index=0).one()
        first.status = CertificateStatus.GENERATED
        first.file_path = "already/done.pdf"
        job.status = JobStatus.PROCESSING
        db.commit()

    rendered = []
    real_render = jobs.render_certificate
    monkeypatch.setattr(
        jobs, "render_certificate", lambda data, path: rendered.append(data.recipient_name) or real_render(data, path)
    )

    jobs.process_job(job.id, session_factory, storage_dir)

    assert rendered == ["Bob Smith", "Chen Wei"]
    with session_factory() as db:
        assert db.get(Job, job.id).status == JobStatus.COMPLETED


def test_unfinished_jobs_are_found_for_resume(session_factory, storage_dir, payload):
    with session_factory() as db:
        done, _ = jobs.create_job(db, JobCreate(**payload()))
        waiting, _ = jobs.create_job(db, JobCreate(**payload()))
    jobs.process_job(done.id, session_factory, storage_dir)

    with session_factory() as db:
        assert jobs.unfinished_job_ids(db) == [waiting.id]


def test_process_job_with_unknown_id_does_nothing(session_factory, storage_dir):
    jobs.process_job("missing", session_factory, storage_dir)  # should not raise
