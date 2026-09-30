from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

_TMP = tempfile.mkdtemp(prefix="atom-tests-")
os.environ.update(
    {
        "ATOM_ENVIRONMENT": "test",
        "ATOM_SECRET": "synthetic-test-session-key-32-characters",
        "ATOM_RUNTIME_TOKEN": "synthetic-test-runtime-key-32-characters",
        "ATOM_DATA_DIR": _TMP,
        "ATOM_DB_PATH": str(Path(_TMP) / "test.db"),
        "ATOM_LLM_API_KEY": "sk-testtesttesttest12",
        "ATOM_LLM_BASE_URL": "https://gateway.invalid/v1",
        "ATOM_LLM_MODEL": "test-model",
        "ATOM_RUNTIME_URL": "http://127.0.0.1:1",
        "ATOM_STARTING_CREDITS": "10",
    }
)

from fastapi.testclient import TestClient  # noqa: E402

from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402


@pytest.fixture
def client() -> Iterator[TestClient]:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def signed_in(client: TestClient) -> TestClient:
    response = client.post(
        "/api/auth/register", json={"email": "builder@example.com", "password": "s3cretpass"}
    )
    assert response.status_code == 200, response.text
    return client
