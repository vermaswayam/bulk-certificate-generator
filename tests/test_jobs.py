"""Creating jobs and checking their status/progress."""


def test_create_job_returns_202_with_job_id(client, payload):
    res = client.post("/api/v1/jobs", json=payload())

    assert res.status_code == 202
    body = res.json()
    assert body["job_id"]
    assert body["status"] == "pending"
    assert body["total_recipients"] == 3
    assert body["accepted"] == 3
    assert body["rejected"] == 0
    assert body["invalid_recipients"] == []
    assert body["status_url"] == f"/api/v1/jobs/{body['job_id']}"
    assert body["certificates_url"] == f"/api/v1/jobs/{body['job_id']}/certificates"


def test_job_status_after_completion(client, create_job):
    job = create_job()

    res = client.get(f"/api/v1/jobs/{job['job_id']}")

    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "completed"
    assert body["course_name"] == "Backend Development with FastAPI"
    assert body["issue_date"] == "2026-10-01"
    assert body["started_at"] is not None
    assert body["completed_at"] is not None
    assert body["progress"] == {
        "total": 3,
        "pending": 0,
        "generated": 3,
        "failed": 0,
        "invalid": 0,
        "percent_complete": 100.0,
    }


def test_progress_for_a_job_that_has_not_run_yet(session_factory, payload):
    from app.schemas import JobCreate
    from app.services.jobs import create_job, get_progress

    with session_factory() as db:
        job, _ = create_job(db, JobCreate(**payload()))
        progress = get_progress(db, job.id)

    assert job.status.value == "pending"
    assert progress.pending == 3
    assert progress.generated == 0
    assert progress.percent_complete == 0.0


def test_issue_date_defaults_to_today(client, create_job):
    from datetime import date

    job = create_job(issue_date=None)

    body = client.get(f"/api/v1/jobs/{job['job_id']}").json()
    assert body["issue_date"] == date.today().isoformat()


def test_unknown_job_returns_404(client):
    assert client.get("/api/v1/jobs/does-not-exist").status_code == 404
    assert client.get("/api/v1/jobs/does-not-exist/certificates").status_code == 404


def test_list_jobs_newest_first(client, create_job):
    first = create_job(course_name="Course A")
    second = create_job(course_name="Course B")

    res = client.get("/api/v1/jobs")

    assert res.status_code == 200
    ids = [j["id"] for j in res.json()]
    assert ids == [second["job_id"], first["job_id"]]


def test_bulk_job_with_many_recipients(client, create_job):
    recipients = [{"name": f"Participant {i}", "email": f"p{i}@example.com"} for i in range(150)]

    job = create_job(recipients)

    body = client.get(f"/api/v1/jobs/{job['job_id']}").json()
    assert body["status"] == "completed"
    assert body["progress"]["generated"] == 150
