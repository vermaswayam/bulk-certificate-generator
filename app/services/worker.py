from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from app.services.jobs import process_job


class JobRunner:
    """Runs jobs on a small in-process thread pool.

    The API returns as soon as the job is saved; generation happens here.
    All state lives in the database, so nothing is lost if the process dies -
    pending jobs are picked up again on startup (see main.lifespan).
    """

    def __init__(self, session_factory: sessionmaker, storage_dir: Path, max_workers: int = 2):
        self.session_factory = session_factory
        self.storage_dir = storage_dir
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="certgen")

    def submit(self, job_id: str) -> None:
        self._executor.submit(process_job, job_id, self.session_factory, self.storage_dir)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


class InlineRunner:
    """Processes the job immediately in the calling thread. Used in tests."""

    def __init__(self, session_factory: sessionmaker, storage_dir: Path):
        self.session_factory = session_factory
        self.storage_dir = storage_dir

    def submit(self, job_id: str) -> None:
        process_job(job_id, self.session_factory, self.storage_dir)

    def shutdown(self) -> None:
        pass
