# Bulk Certificate Generator

![tests](https://github.com/<your-username>/<repo-name>/actions/workflows/tests.yml/badge.svg)

**Live demo:** <add your Render URL here> (free tier: first request may take ~1 min to wake up, data resets on restart)

A backend API that takes a list of recipients plus course/event details and generates a PDF certificate for each one from a single predefined template. Generation runs in the background. You can track a job's progress, see exactly which recipients failed and why, and download the certificates one at a time or as a ZIP.

**Stack:** Python 3.11+, FastAPI, SQLAlchemy 2 (SQLite by default; any relational DB via `DATABASE_URL`), ReportLab for the PDFs, and pytest.

**Features**
- One request generates certificates for up to 1000 recipients (JSON body **or CSV upload**)
- Per-recipient validation: bad rows are reported, valid rows still get certificates
- Background generation with live progress; jobs resume after a restart
- One failing certificate never stops the others; failed ones can be retried
- Download a single PDF or the whole job as a ZIP
- Each certificate carries a verifiable certificate ID
- A small demo web page at `/`, Docker setup, and CI running the test suite on every push

---

## Setup

```bash
git clone <repo-url>
cd <repo>

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements-dev.txt   # app + test tools (requirements.txt is app only)
```

You don't need any API keys or external services. Configuration is optional. Copy `.env.example` to `.env` if you want to change anything:

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./certificates.db` | Any SQLAlchemy URL (e.g. Postgres) |
| `STORAGE_DIR` | `./storage` | Where generated PDFs are written |
| `MAX_RECIPIENTS_PER_JOB` | `1000` | Upper limit per request |
| `WORKER_THREADS` | `2` | How many jobs are processed in parallel |

## Running the application

```bash
uvicorn app.main:app --reload
```

- Demo page: http://127.0.0.1:8000
- Interactive API docs (Swagger): http://127.0.0.1:8000/docs

Tables are created automatically on startup.

### With Docker

```bash
docker compose up --build
```

Same URLs as above. The database and PDFs are kept in a Docker volume (`certdata`), so they survive restarts.

### Demo page

The page at `/` is a thin client over the same public API (plain HTML + JavaScript in `app/static/index.html`, no build step). You can paste recipients or upload a CSV, watch the progress bar update, filter results by status, download PDFs or the ZIP, retry failed certificates, and verify a certificate ID. It exists so reviewers can see the whole flow without writing curl commands. All the logic stays in the backend.

## Running the tests

```bash
pytest
```

GitHub Actions runs the same suite on every push (`.github/workflows/tests.yml`).

The tests use a temporary SQLite database and storage folder per test, so they never touch your real data. Jobs run inline in tests (same thread), so results can be checked right after the POST.

| File | What it covers |
|---|---|
| `tests/test_jobs.py` | creating a job, job status & progress, listing jobs, 150-recipient bulk job |
| `tests/test_validation.py` | request-level validation, per-recipient validation, duplicates, all-invalid request |
| `tests/test_generation.py` | the PDF template, the job processor, resuming an interrupted job |
| `tests/test_failures.py` | one certificate failing while the others succeed, all failing, retry, unexpected crash |
| `tests/test_retrieval.py` | listing/filtering, single PDF download, ZIP download, error cases, verification |
| `tests/test_csv_upload.py` | CSV upload, missing columns, size limit, Excel encodings/BOM, demo page |

---

## API overview

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/jobs` | Submit a bulk generation request (returns `202` + job id) |
| `POST` | `/api/v1/jobs/csv` | Same, but recipients come from an uploaded CSV file |
| `GET` | `/api/v1/jobs` | List recent jobs |
| `GET` | `/api/v1/jobs/{job_id}` | Job status and progress counts |
| `GET` | `/api/v1/jobs/{job_id}/certificates` | Per-recipient results (`?status=generated\|failed\|invalid\|pending`, `limit`, `offset`) |
| `GET` | `/api/v1/jobs/{job_id}/certificates/archive` | ZIP of all generated certificates |
| `POST` | `/api/v1/jobs/{job_id}/retry` | Retry certificates whose generation failed |
| `GET` | `/api/v1/certificates/{id}` | One certificate's details |
| `GET` | `/api/v1/certificates/{id}/download` | Download one certificate (PDF) |
| `GET` | `/api/v1/verify/{code}` | Verify a certificate by the ID printed on it |
| `GET` | `/health` | Health check |

### Submitting a certificate generation request

```bash
curl -X POST http://127.0.0.1:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d @examples/sample_request.json
```

PowerShell:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/jobs `
  -ContentType "application/json" -InFile examples/sample_request.json
```

Request body:

```json
{
  "course_name": "Backend Development with FastAPI",
  "issuer": "Acme Academy",
  "issue_date": "2026-10-01",
  "recipients": [
    { "name": "Alice Johnson", "email": "alice@example.com" },
    { "name": "Bob Smith", "email": "bob@example.com" },
    { "name": "Bad Email", "email": "not-an-email" }
  ]
}
```

`issue_date` is optional (defaults to today).

Or upload a CSV with `name` and `email` columns (see `examples/sample_recipients.csv`):

```bash
curl -X POST http://127.0.0.1:8000/api/v1/jobs/csv   -F file=@examples/sample_recipients.csv   -F "course_name=Machine Learning Bootcamp"   -F "issuer=Acme Academy"
```

Response (`202 Accepted`, same for both):

```json
{
  "job_id": "04941a84-ff7e-4de8-af47-cd52f2d94bbf",
  "status": "pending",
  "total_recipients": 3,
  "accepted": 2,
  "rejected": 1,
  "invalid_recipients": [
    { "index": 2, "errors": ["email: value is not a valid email address: An email address must have an @-sign."] }
  ],
  "status_url": "/api/v1/jobs/04941a84-...",
  "certificates_url": "/api/v1/jobs/04941a84-.../certificates"
}
```

### Checking progress

```bash
curl http://127.0.0.1:8000/api/v1/jobs/<job_id>
```

```json
{
  "id": "04941a84-...",
  "status": "completed_with_errors",
  "progress": {
    "total": 3, "pending": 0, "generated": 2, "failed": 0, "invalid": 1,
    "percent_complete": 100.0
  },
  "...": "..."
}
```

Job statuses: `pending` → `processing` → `completed` | `completed_with_errors` | `failed`.

Certificate statuses:
- `pending`: waiting to be generated
- `generated`: the PDF is ready
- `failed`: the input was valid but generation broke (can be retried)
- `invalid`: the input was rejected at validation and never attempted

### Retrieving generated certificates

```bash
# per-recipient list with download links (and errors for the ones that didn't work)
curl "http://127.0.0.1:8000/api/v1/jobs/<job_id>/certificates"
curl "http://127.0.0.1:8000/api/v1/jobs/<job_id>/certificates?status=failed"

# one PDF
curl -o alice.pdf http://127.0.0.1:8000/api/v1/certificates/<certificate_id>/download

# everything as a ZIP
curl -o certificates.zip http://127.0.0.1:8000/api/v1/jobs/<job_id>/certificates/archive
```

Files in the ZIP are named `<row number>_<name>.pdf` (e.g. `0001_Alice_Johnson.pdf`) so they line up with the order of the original request.

---

## Design decisions

### Background processing (and why not Celery)
A request can contain up to 1000 recipients, so generating everything inside the HTTP request would make the client wait a long time and risk timeouts. Instead, `POST /jobs` validates the input, saves the job and one row per recipient, and returns `202` straight away. A small in-process `ThreadPoolExecutor` (`app/services/worker.py`) then does the generation.

I chose a thread pool over Celery/RQ to keep the project runnable with zero extra infrastructure (no Redis or RabbitMQ). The trade-off is that a thread pool can't be scaled out across machines. That's acceptable here because:

- **All state lives in the database**, not in memory. The worker only processes certificates that are still `pending`.
- **Jobs are resumed on startup.** If the server stops mid-job, any `pending`/`processing` jobs are picked up again when it restarts, and certificates already generated are not redone.
- Rendering one PDF is CPU-light and mostly I/O, so threads are fine here despite the GIL.

Moving to Celery later would be a small change: `JobRunner.submit()` would call `process_job.delay(job_id)` instead, and nothing else would need to change.

### Validation is per recipient, not all-or-nothing
There are two levels of validation:
1. **Request level** (FastAPI/Pydantic): `course_name`, `issuer` and `issue_date` must be valid, and `recipients` must have between 1 and `MAX_RECIPIENTS_PER_JOB` entries. If any of this is wrong, the whole request gets a `422`.
2. **Recipient level** (`app/services/validation.py`): each recipient is validated on its own (name 1–100 printable characters, valid email, no duplicate emails in the same request). Invalid recipients **don't reject the request**. They come back in `invalid_recipients` with their index and reason, and are stored on the job with status `invalid`. Only if *every* recipient is invalid does the API return `422`, since there would be nothing to do.

I picked this because with a list of 500 people, one typo shouldn't block 499 certificates. The client gets a clear list of rows to fix.

### Failure isolation
Each certificate is generated inside its own `try/except` (`_generate_one` in `app/services/jobs.py`). If rendering one fails, that certificate is marked `failed` with the error message, and the loop continues. The job ends as `completed_with_errors`, and `GET /jobs/{id}/certificates?status=failed` shows exactly who failed and why. `POST /jobs/{id}/retry` re-queues only the `failed` ones. `invalid` ones aren't retried because they would fail the same way again.

If something unexpected breaks the job as a whole (e.g. the database goes away), the job is marked `failed` with the error instead of being stuck in `processing` forever.

### Progress tracking
Progress is calculated from the certificate rows with one `GROUP BY status` query, so it can never get out of sync with the real data. The worker commits after every certificate, so progress updates live while a big job is running.

### Certificate template
`app/services/pdf.py` holds the single template: a landscape A4 PDF drawn with ReportLab. ReportLab needs no system dependencies, which keeps setup to a single `pip install`. Long names and course titles automatically shrink to fit on one line. Each PDF is written to a temp file and then renamed, so a crash never leaves a half-written certificate behind. Every certificate gets a random **certificate ID** printed at the bottom, which can be checked with `GET /api/v1/verify/{code}`.

The template uses the standard PDF fonts, which only cover Latin characters (accents like é/ü are fine). Names outside that range (e.g. Devanagari or Chinese) are rejected at validation with a clear message, rather than producing a certificate with empty boxes. Supporting them would mean bundling a Unicode TTF font and registering it with ReportLab.

### CSV upload
The CSV endpoint only parses the file into the same list of recipients the JSON endpoint takes, then goes through exactly the same code path (`_submit_job`). Validation rules live in one place. Header names are matched case-insensitively, extra columns are ignored, fully blank rows are skipped, and both UTF-8 (with or without Excel's BOM) and Windows-1252 files are accepted. Files are capped at 2 MB, and the 1000-recipient limit still applies.

### Storage
PDFs are stored on disk under `STORAGE_DIR/<job_id>/<certificate_id>.pdf`, and the database stores the path relative to `STORAGE_DIR`, so the folder can be moved. In production I would swap this for S3 (or similar) and return pre-signed URLs.

### Database
SQLite keeps local setup to zero steps. WAL mode is turned on so the API can read progress while the worker writes. The code only uses plain SQLAlchemy, so pointing `DATABASE_URL` at PostgreSQL or MySQL works without code changes (just install the driver).

## Deploying (Render)

The repo includes a `Dockerfile` and a `render.yaml` blueprint:

1. Push the repo to GitHub.
2. On [render.com](https://render.com): **New + → Blueprint** → select the repo → **Apply**.
3. Once it's live, open the URL. The demo page is at `/` and the API docs at `/docs`.

On the free plan there is no persistent disk, so the SQLite database and generated PDFs are wiped whenever the service restarts or redeploys, and the service sleeps after ~15 minutes idle. For a real deployment I'd use a managed PostgreSQL (`DATABASE_URL`) and S3 for the files.

## Project structure

```
app/
  main.py              # FastAPI app, startup (create tables, start worker, resume jobs)
  config.py            # settings from env / .env
  database.py          # engine, session, SQLite pragmas
  models.py            # Job and Certificate tables + status enums
  schemas.py           # request/response models, recipient validation rules
  routes.py            # API endpoints
  static/index.html    # demo page
  dependencies.py      # injectable runner/storage (overridden in tests)
  services/
    validation.py      # per-recipient validation
    csv_import.py      # CSV file -> list of recipients
    pdf.py             # the certificate template
    jobs.py            # create job, process job, progress, retry
    worker.py          # background thread pool runner
tests/                 # pytest suite
examples/
  sample_request.json     # example JSON request with some invalid rows
  sample_recipients.csv   # example CSV upload
Dockerfile, docker-compose.yml, render.yaml
.github/workflows/tests.yml   # CI
```

## What I'd add with more time
- Alembic migrations instead of `create_all`
- A real task queue (Celery/RQ + Redis) to scale workers across machines
- Object storage (S3) with pre-signed download URLs
- Authentication / per-organisation API keys
- Emailing certificates to recipients
