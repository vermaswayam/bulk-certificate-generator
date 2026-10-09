from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = f"sqlite:///{BASE_DIR / 'certificates.db'}"
    storage_dir: Path = BASE_DIR / "storage"
    max_recipients_per_job: int = 1000
    worker_threads: int = 2


settings = Settings()
