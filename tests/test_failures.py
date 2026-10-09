"""A failure on one certificate must not break the rest of the job."""

import pytest

from app.services import jobs


@pytest.fixture
def fail_for(monkeypatch):
    """Make rendering blow up for the given recipient names."""
    real_render = jobs.render_certificate

    def _install(*names):
        def flaky_render(data, path):
            if data.recipient_name in names:
                raise RuntimeError(f"renderer crashed on {data.recipient_name}")
            return real_render(data, path)

        monkeypatch.setattr(jobs, "render_certificate", flaky_render)

    yield _install
    monkeypatch.setattr(jobs, "render_certificate", real_render)


def test_one_failure_does_not_stop_other_certificates(client, create_job, fail_for):
    fail_for("Bob Smith")

    job = create_job()

    status = client.get(job["status_url"]).json()
    assert status["status"] == "completed_with_errors"
    assert status["progress"]["generated"] == 2
    assert status["progress"]["failed"] == 1

    failed = client.get(job["certificates_url"], params={"status": "failed"}).json()
    assert failed["total"] == 1
    item = failed["items"][0]
    assert item["recipient_name"] == "Bob Smith"
    assert item["row_index"] == 1
    assert item["error"] == "RuntimeError: renderer crashed on Bob Smith"
    assert item["download_url"] is None

    generated = client.get(job["certificates_url"], params={"status": "generated"}).json()
    assert [c["recipient_name"] for c in generated["items"]] == ["Alice Johnson", "Chen Wei"]


def test_job_fails_when_nothing_could_be_generated(client, create_job, fail_for):
    fail_for("Alice Johnson", "Bob Smith", "Chen Wei")

    job = create_job()

    status = client.get(job["status_url"]).json()
    assert status["status"] == "failed"
    assert status["error"] == "no certificates could be generated"
    assert status["progress"]["failed"] == 3


def test_retry_regenerates_only_failed_certificates(client, create_job, fail_for, monkeypatch):
    fail_for("Bob Smith")
    job = create_job()
    # "fix" the problem, then retry
    monkeypatch.undo()

    res = client.post(f"/api/v1/jobs/{job['job_id']}/retry")

    assert res.status_code == 202
    status = client.get(job["status_url"]).json()
    assert status["status"] == "completed"
    assert status["progress"]["generated"] == 3
    assert status["progress"]["failed"] == 0


def test_retry_is_rejected_when_nothing_failed(client, create_job):
    job = create_job()

    res = client.post(f"/api/v1/jobs/{job['job_id']}/retry")

    assert res.status_code == 409


def test_unexpected_crash_marks_job_failed(client, create_job, monkeypatch):
    def boom(db, job_id):
        raise RuntimeError("database went away")

    monkeypatch.setattr(jobs, "get_progress", boom)
    job = create_job()
    monkeypatch.undo()

    status = client.get(job["status_url"]).json()
    assert status["status"] == "failed"
    assert "database went away" in status["error"]
