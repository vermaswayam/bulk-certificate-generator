"""Downloading and looking up generated certificates."""

import io
import zipfile

from app.services import jobs


def test_list_certificates_has_download_links(client, create_job):
    job = create_job()

    res = client.get(job["certificates_url"])

    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 3
    assert [c["row_index"] for c in body["items"]] == [0, 1, 2]
    for cert in body["items"]:
        assert cert["status"] == "generated"
        assert cert["download_url"] == f"/api/v1/certificates/{cert['id']}/download"


def test_list_certificates_pagination(client, create_job):
    job = create_job()

    body = client.get(job["certificates_url"], params={"limit": 2, "offset": 2}).json()

    assert body["total"] == 3
    assert [c["recipient_name"] for c in body["items"]] == ["Chen Wei"]


def test_download_single_certificate(client, create_job):
    job = create_job()
    cert = client.get(job["certificates_url"]).json()["items"][0]

    res = client.get(cert["download_url"])

    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert 'filename="certificate_Alice_Johnson.pdf"' in res.headers["content-disposition"]
    assert res.content.startswith(b"%PDF-")


def test_get_certificate_details(client, create_job):
    job = create_job()
    cert = client.get(job["certificates_url"]).json()["items"][1]

    res = client.get(f"/api/v1/certificates/{cert['id']}")

    assert res.status_code == 200
    assert res.json()["recipient_email"] == "bob@example.com"


def test_download_unknown_certificate_returns_404(client):
    assert client.get("/api/v1/certificates/nope").status_code == 404
    assert client.get("/api/v1/certificates/nope/download").status_code == 404


def test_download_invalid_certificate_returns_409(client, create_job):
    job = create_job(
        [
            {"name": "Alice Johnson", "email": "alice@example.com"},
            {"name": "Broken", "email": "broken"},
        ]
    )
    invalid = client.get(job["certificates_url"], params={"status": "invalid"}).json()["items"][0]

    res = client.get(f"/api/v1/certificates/{invalid['id']}/download")

    assert res.status_code == 409
    assert "invalid" in res.json()["detail"]


def test_download_missing_file_returns_410(client, create_job, storage_dir):
    job = create_job()
    cert = client.get(job["certificates_url"]).json()["items"][0]
    for pdf in storage_dir.rglob("*.pdf"):
        pdf.unlink()

    assert client.get(cert["download_url"]).status_code == 410


def test_download_job_archive(client, create_job):
    job = create_job()

    res = client.get(f"/api/v1/jobs/{job['job_id']}/certificates/archive")

    assert res.status_code == 200
    assert res.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
        assert zf.namelist() == ["0001_Alice_Johnson.pdf", "0002_Bob_Smith.pdf", "0003_Chen_Wei.pdf"]
        assert zf.read("0001_Alice_Johnson.pdf").startswith(b"%PDF-")


def test_archive_skips_failed_certificates(client, create_job, monkeypatch):
    real_render = jobs.render_certificate

    def flaky(data, path):
        if data.recipient_name == "Bob Smith":
            raise RuntimeError("nope")
        return real_render(data, path)

    monkeypatch.setattr(jobs, "render_certificate", flaky)
    job = create_job()

    res = client.get(f"/api/v1/jobs/{job['job_id']}/certificates/archive")

    with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
        assert zf.namelist() == ["0001_Alice_Johnson.pdf", "0003_Chen_Wei.pdf"]


def test_archive_with_nothing_generated_returns_409(client, create_job, monkeypatch):
    monkeypatch.setattr(jobs, "render_certificate", lambda data, path: (_ for _ in ()).throw(OSError("disk full")))
    job = create_job()

    res = client.get(f"/api/v1/jobs/{job['job_id']}/certificates/archive")

    assert res.status_code == 409


def test_verify_certificate_by_code(client, create_job):
    job = create_job()
    cert = client.get(job["certificates_url"]).json()["items"][0]

    res = client.get(f"/api/v1/verify/{cert['verification_code'].lower()}")

    assert res.status_code == 200
    assert res.json() == {
        "valid": True,
        "recipient_name": "Alice Johnson",
        "course_name": "Backend Development with FastAPI",
        "issuer": "Acme Academy",
        "issue_date": "2026-10-01",
    }
    assert client.get("/api/v1/verify/FFFFFFFFFFFF").status_code == 404
