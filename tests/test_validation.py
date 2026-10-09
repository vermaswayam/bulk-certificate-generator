"""Request-level and per-recipient validation."""

import pytest

from app.config import settings
from app.services.validation import validate_recipients


@pytest.mark.parametrize("field", ["course_name", "issuer"])
def test_missing_job_field_is_rejected(client, payload, field):
    body = payload()
    del body[field]

    res = client.post("/api/v1/jobs", json=body)

    assert res.status_code == 422


def test_blank_course_name_is_rejected(client, payload):
    res = client.post("/api/v1/jobs", json=payload(course_name="   "))
    assert res.status_code == 422


def test_bad_issue_date_is_rejected(client, payload):
    res = client.post("/api/v1/jobs", json=payload(issue_date="31-31-2026"))
    assert res.status_code == 422


def test_empty_recipient_list_is_rejected(client, payload):
    res = client.post("/api/v1/jobs", json=payload(recipients=[]))
    assert res.status_code == 422


def test_too_many_recipients_is_rejected(client, payload, monkeypatch):
    monkeypatch.setattr(settings, "max_recipients_per_job", 2)

    res = client.post("/api/v1/jobs", json=payload())

    assert res.status_code == 422
    assert "at most 2 recipients" in res.text


def test_invalid_recipients_are_reported_but_valid_ones_still_processed(client, payload):
    recipients = [
        {"name": "Alice Johnson", "email": "alice@example.com"},
        {"name": "", "email": "empty-name@example.com"},
        {"name": "Bad Email", "email": "not-an-email"},
        {"name": "Dana Lee", "email": "dana@example.com"},
    ]

    res = client.post("/api/v1/jobs", json=payload(recipients))

    assert res.status_code == 202
    body = res.json()
    assert body["accepted"] == 2
    assert body["rejected"] == 2
    assert [r["index"] for r in body["invalid_recipients"]] == [1, 2]
    assert "name" in body["invalid_recipients"][0]["errors"][0]
    assert "email" in body["invalid_recipients"][1]["errors"][0]

    job = client.get(body["status_url"]).json()
    assert job["status"] == "completed_with_errors"
    assert job["progress"]["generated"] == 2
    assert job["progress"]["invalid"] == 2

    invalid = client.get(body["certificates_url"], params={"status": "invalid"}).json()
    assert invalid["total"] == 2
    assert invalid["items"][1]["recipient_name"] == "Bad Email"
    assert invalid["items"][1]["error"].startswith("email:")
    assert invalid["items"][1]["download_url"] is None


def test_all_recipients_invalid_rejects_request(client, payload):
    res = client.post("/api/v1/jobs", json=payload([{"name": "No Email"}, "just a string"]))

    assert res.status_code == 422
    detail = res.json()["detail"]
    assert detail["message"] == "none of the recipients are valid"
    assert [r["index"] for r in detail["invalid_recipients"]] == [0, 1]


def test_validate_recipients_collects_each_problem():
    valid, invalid = validate_recipients(
        [
            {"name": "  Alice  ", "email": "alice@example.com"},
            {"name": "Alice Again", "email": "ALICE@example.com"},  # duplicate, case-insensitive
            {"email": "x@example.com"},                            # missing name
            {"name": "A" * 101, "email": "long@example.com"},     # too long
            {"name": "Tab\tName", "email": "tab@example.com"},     # control character
            42,                                                    # not an object
            {"name": "राहुल", "email": "rahul@example.com"},       # outside the font's charset
            {"name": "José Müller", "email": "jose@example.com"},  # accents are fine
        ]
    )

    assert [(i, r.name) for i, r in valid] == [(0, "Alice"), (7, "José Müller")]  # whitespace stripped
    by_index = {row.index: row for row in invalid}
    assert set(by_index) == {1, 2, 3, 4, 5, 6}
    assert "cannot display" in by_index[6].errors[0]
    assert "duplicate" in by_index[1].errors[0]
    assert by_index[2].errors[0].startswith("name:")
    assert by_index[3].errors[0].startswith("name:")
    assert "control characters" in by_index[4].errors[0]
    assert by_index[5].name is None
