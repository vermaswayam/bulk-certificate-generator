from pathlib import Path

from fastapi import Request

from app.config import settings


def get_runner(request: Request):
    return request.app.state.runner


def get_storage_dir() -> Path:
    return settings.storage_dir
