import pytest

from app import settings


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    """Point every storage path at a throwaway tmp dir so tests never touch ./storage."""
    monkeypatch.setattr(settings, "STORAGE_DIR", tmp_path)
    monkeypatch.setattr(settings, "ROUTINES_DIR", tmp_path / "routines")
    monkeypatch.setattr(settings, "LOGS_DIR", tmp_path / "logs")
    yield
