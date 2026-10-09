import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.config import settings
from app.database import Base, SessionLocal, engine
from app.routes import router
from app.services.jobs import unfinished_job_ids
from app.services.worker import JobRunner

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    settings.storage_dir.mkdir(parents=True, exist_ok=True)

    runner = JobRunner(SessionLocal, settings.storage_dir, settings.worker_threads)
    app.state.runner = runner

    # pick up anything that was queued or mid-way when the server last stopped
    with SessionLocal() as db:
        for job_id in unfinished_job_ids(db):
            logger.info("resuming unfinished job %s", job_id)
            runner.submit(job_id)

    yield
    runner.shutdown()


app = FastAPI(
    title="Bulk Certificate Generator",
    version="1.0.0",
    description="Submit a list of recipients, generate a PDF certificate for each, track progress and download the results.",
    lifespan=lifespan,
)
app.include_router(router)

STATIC_DIR = Path(__file__).parent / "static"


@app.get("/", include_in_schema=False)
def demo_page():
    """Small demo UI on top of the API (plain HTML + JS, no build step)."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}
