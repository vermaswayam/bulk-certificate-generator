"""Creating a job from an uploaded CSV file."""

import pytest

from app.services.csv_import import CSVError, parse_recipients_csv

FORM = {"course_name": "Intro to Python", "issuer": "Acme Academy", "issue_date": "2026-10-01"}


def upload(client, content: bytes, **form):
    return client.post(
        "/api/v1/jobs/csv",
        data={**FORM, **form},
        files={"file": ("recipients.csv", content, "text/csv")},
    )


def test_csv_upload_creates_job(client):
    csv = b"name,email\nAlice Johnson,alice@example.com\nBob Smith,bob@example.com\n"

    res = upload(client, csv)

    assert res.status_code == 202
    body = res.json()
    assert body["accepted"] == 2
    job = client.get(body["status_url"]).json()
    assert job["status"] == "completed"
    assert job["course_name"] == "Intro to Python"
    assert job["progress"]["generated"] == 2


def test_csv_invalid_rows_are_reported(client):
    csv = b"name,email\nAlice Johnson,alice@example.com\n,nobody@example.com\nBad,not-an-email\n"

    body = upload(client, csv).json()

    assert body["accepted"] == 1
    assert [r["index"] for r in body["invalid_recipients"]] == [1, 2]


def test_csv_missing_column_is_rejected(client):
    res = upload(client, b"full_name,email\nAlice,alice@example.com\n")

    assert res.status_code == 422
    assert res.json()["detail"] == "CSV is missing column(s): name"


def test_csv_missing_form_field_is_rejected(client):
    res = client.post(
        "/api/v1/jobs/csv",
        data={"issuer": "Acme"},
        files={"file": ("r.csv", b"name,email\nA,a@example.com\n", "text/csv")},
    )
    assert res.status_code == 422


def test_csv_with_no_rows_is_rejected(client):
    res = upload(client, b"name,email\n")

    assert res.status_code == 422
    assert "recipients" in res.json()["detail"][0]


def test_csv_too_large_is_rejected(client, monkeypatch):
    from app import routes

    monkeypatch.setattr(routes, "MAX_CSV_BYTES", 10)

    res = upload(client, b"name,email\nAlice,alice@example.com\n")

    assert res.status_code == 413


def test_parse_handles_excel_quirks():
    # BOM, odd header casing/spacing, extra columns, blank trailing rows
    raw = "﻿Name , EMAIL,score\nJosé Müller,jose@example.com,90\n,,\n".encode("utf-8")

    assert parse_recipients_csv(raw) == [{"name": "José Müller", "email": "jose@example.com"}]


def test_parse_falls_back_to_windows_encoding():
    raw = "name,email\nJosé,jose@example.com\n".encode("cp1252")

    assert parse_recipients_csv(raw)[0]["name"] == "José"


def test_parse_empty_file():
    with pytest.raises(CSVError, match="empty"):
        parse_recipients_csv(b"")


def test_demo_page_is_served(client):
    res = client.get("/")

    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "Bulk Certificate Generator" in res.text
