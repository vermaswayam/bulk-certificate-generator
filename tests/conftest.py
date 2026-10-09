import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db, make_engine
from app.dependencies import get_runner, get_storage_dir
from app.main import app
from app.services.worker import InlineRunner


@pytest.fixture
def session_factory(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def storage_dir(tmp_path):
    path = tmp_path / "storage"
    path.mkdir()
    return path


@pytest.fixture
def client(session_factory, storage_dir):
    # Jobs run inline in tests so the result is ready as soon as POST returns.
    runner = InlineRunner(session_factory, storage_dir)

    def override_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_runner] = lambda: runner
    app.dependency_overrides[get_storage_dir] = lambda: storage_dir
    # not using `with TestClient(...)` on purpose: that would run the real
    # lifespan against the real database
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def payload():
    def _make(recipients=None, **overrides):
        body = {
            "course_name": "Backend Development with FastAPI",
            "issuer": "Acme Academy",
            "issue_date": "2026-10-01",
            "recipients": recipients
            if recipients is not None
            else [
                {"name": "Alice Johnson", "email": "alice@example.com"},
                {"name": "Bob Smith", "email": "bob@example.com"},
                {"name": "Chen Wei", "email": "chen@example.com"},
            ],
        }
        body.update(overrides)
        return body

    return _make


@pytest.fixture
def create_job(client, payload):
    def _create(recipients=None, **overrides):
        res = client.post("/api/v1/jobs", json=payload(recipients, **overrides))
        assert res.status_code == 202, res.text
        return res.json()

    return _create
