import os
import tempfile
from pathlib import Path

_dir = Path(tempfile.mkdtemp())
os.environ["ATOM_DB_PATH"] = str(_dir / "test.db")
os.environ["ATOM_SECRET"] = "test-secret"
os.environ["ATOM_LLM_API_KEY"] = "sk-testkeyAB"
os.environ["ATOM_LLM_BASE_URL"] = "https://example.test/v1"
os.environ["ATOM_LLM_MODEL"] = "claude-haiku-4-5"
os.environ["ATOM_DAILY_CALL_LIMIT"] = "40"

import pytest
from fastapi.testclient import TestClient

from app.db import Base, engine
from app.main import app


@pytest.fixture()
def client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as test_client:
        yield test_client
