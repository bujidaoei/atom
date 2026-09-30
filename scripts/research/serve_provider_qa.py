"""Bounded local browser QA, using actual API and isolated synthetic provider.

This fixture tests connection UX only, not real model generation. It never loads
.env or production storage. Run using backend's Python environment.
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import secrets
import sys
import tempfile
from threading import Thread, Timer


def main() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
    from app import config
    import uvicorn

    class Provider(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"data": [{"id": "qa-connection-only"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    with tempfile.TemporaryDirectory(prefix="atom-browser-qa-") as folder:
        root = Path(folder)
        for name in ("projects", "published"):
            (root / name).mkdir()
        settings = config.Settings(
            _env_file=None, environment="test", secret=secrets.token_hex(32),
            runtime_token=secrets.token_hex(32), cookie_secure=False,
            data_dir=root, db_path=root / "qa.db",
            llm_base_url="http://127.0.0.1:18723/managed",
            llm_api_key="synthetic-qa-managed", runtime_url="http://127.0.0.1:1",
        )
        config.get_settings = lambda: settings
        from app.db import engine, session_scope
        from app.models import Base, User, UserSettings
        from app.security import hash_password
        from app.main import app

        Base.metadata.create_all(engine)
        with session_scope() as db:
            user = User(email="qa@example.com", name="Connection QA", password_hash=hash_password("Browser-check-2048!"))
            db.add(user)
            db.flush()
            db.add(UserSettings(user_id=user.id, base_url="http://127.0.0.1:18723/legacy", api_key=None))
        provider = ThreadingHTTPServer(("127.0.0.1", 18723), Provider)
        thread = Thread(target=provider.serve_forever, daemon=True)
        thread.start()
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=18724, log_level="warning"))
        def stop():
            server.should_exit = True
        deadline = Timer(900, stop)
        deadline.daemon = True
        deadline.start()
        print("QA API on 127.0.0.1:18724; automatic shutdown in 900 seconds", flush=True)
        try:
            server.run()
        finally:
            deadline.cancel()
            provider.shutdown()
            provider.server_close()
            thread.join(timeout=5)
            engine.dispose()


if __name__ == "__main__":
    main()
