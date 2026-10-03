"""Opt-in authenticated origin/proof denial in the exact serving image.

Runs in-process against a disposable database. No production session, server,
network or browser credential is read or changed.
"""

from contextlib import closing
import os
from pathlib import Path
import secrets
import sqlite3
import tempfile
import unittest
from urllib.parse import urlparse

if os.environ.get("ATOM_IMAGE_AUTH_DRILL") == "1":
    # Never read the serving deployment's .env or reuse its signing secrets.
    os.environ["ATOM_SECRET"] = secrets.token_urlsafe(48)
    os.environ["ATOM_RUNTIME_TOKEN"] = secrets.token_urlsafe(48)

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.main import app
from app.migrations import migrate
from app.models import Base


@unittest.skipUnless(os.environ.get("ATOM_IMAGE_AUTH_DRILL") == "1",
                     "explicit exact-image authentication drill opt-in required")
class ConsoleIpBoundaryImageTest(unittest.TestCase):
    def test_valid_session_and_proof_cannot_write_from_public_port(self):
        console = os.environ["ATOM_DRILL_CONSOLE_ORIGIN"]
        public = os.environ["ATOM_DRILL_PUBLIC_ORIGIN"]
        console_url, public_url = urlparse(console), urlparse(public)
        self.assertEqual(console_url.scheme, "https")
        self.assertEqual(public_url.scheme, "https")
        self.assertEqual(console_url.hostname, public_url.hostname)
        self.assertIsNone(console_url.port)
        self.assertGreater(public_url.port or 0, 0)
        self.assertEqual(console_url.path, "")
        self.assertEqual(public_url.path, "")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "atom.db"
            engine = create_engine(f"sqlite:///{database}",
                                   connect_args={"check_same_thread": False})
            Base.metadata.create_all(engine)
            for version in range(1, 19):
                migrate(database, root / f"before-v{version}.db",
                        target_version=version)
            settings = get_settings()
            original = {name: getattr(settings, name) for name in
                        ("db_path", "session_mode", "console_origin",
                         "console_proof_required", "cookie_secure",
                         "cookie_path", "ip_preview_enabled")}
            settings.db_path = database
            settings.session_mode = "durable"
            settings.console_origin = console
            settings.console_proof_required = True
            settings.cookie_secure = True
            settings.cookie_path = "/"
            settings.ip_preview_enabled = False

            def sessions():
                with Session(engine, expire_on_commit=False) as session:
                    yield session

            app.dependency_overrides[get_db] = sessions
            identity = secrets.token_hex(8)
            credentials = {"email": f"boundary-{identity}@example.org",
                           "password": secrets.token_urlsafe(24)}
            try:
                with TestClient(app, base_url=console,
                                headers={"Origin": console}) as client:
                    registered = client.post("/api/auth/register",
                                             json=credentials)
                    self.assertEqual(registered.status_code, 200)
                    proof = registered.json()["consoleProof"]
                    self.assertTrue(proof)
                    valid = {"X-Atom-Console-Proof": proof}
                    self.assertEqual(client.get("/api/auth/me",
                                                headers=valid).status_code, 200)
                    # Valid cookie and proof travel with the request. Only
                    # the cross-port Origin is hostile; the body would create
                    # a project if the server accepted it.
                    denied = client.post("/api/projects",
                        json={"prompt": "Boundary drill should not create a project"},
                        headers=valid | {"Origin": public})
                    self.assertEqual(denied.status_code, 403)
                    host_denied = client.post("/api/projects",
                        json={"prompt": "Boundary drill should not create a project"},
                        headers=valid | {"Host": public_url.netloc})
                    self.assertEqual(host_denied.status_code, 403)
                    self.assertEqual(client.get("/api/auth/me",
                                                headers=valid).status_code, 200)
                with closing(sqlite3.connect(database)) as db:
                    self.assertEqual(db.execute(
                        "SELECT count(*) FROM projects").fetchone(), (0,))
                    self.assertEqual(db.execute(
                        "SELECT count(*) FROM console_sessions "
                        "WHERE revoked_at IS NULL").fetchone(), (1,))
            finally:
                app.dependency_overrides.pop(get_db, None)
                for name, value in original.items():
                    setattr(settings, name, value)
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
