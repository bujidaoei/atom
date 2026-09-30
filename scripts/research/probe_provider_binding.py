"""Read-only product probe using a temporary DB and a synthetic loopback provider.

Run with backend's Python environment. Does not load .env, contact a real model,
or expose captured header values. Exit 1 means the unsafe binding was observed;
exit 0 means not observed by this narrow probe, not full security acceptance.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread


def main() -> int:
    repo = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo / "backend"))
    # Only loopback traffic is expected; environment proxies must not receive it.
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"
    synthetic_key = "probe-" + secrets.token_hex(24)
    observed: list[bool] = []

    class Capture(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            observed.append(self.headers.get("Authorization") == f"Bearer {synthetic_key}")
            body = b'{"data":[{"id":"probe-model"}]}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    with tempfile.TemporaryDirectory(prefix="atom-provider-probe-") as directory:
        from app import config

        root = Path(directory)
        # Replaces configuration source only; actual settings resolver, SQLAlchemy
        # session, HTTP client and HTTP receiver execute without transport mocks.
        settings = config.Settings(
            _env_file=None,
            data_dir=root,
            db_path=root / "probe.db",
            llm_base_url="https://managed-provider.invalid/v1",
            llm_api_key=synthetic_key,
            runtime_url="http://127.0.0.1:1",
        )
        config.get_settings = lambda: settings

        from app.db import engine, SessionLocal
        from app.models import Base, User, UserSettings
        from app.routers.settings import _payload

        server = ThreadingHTTPServer(("127.0.0.1", 0), Capture)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            Base.metadata.create_all(engine)
            with SessionLocal() as session:
                user = User(email="probe@example.invalid", name="Probe", password_hash="unused")
                session.add(user)
                session.flush()
                session.add(UserSettings(
                    user_id=user.id,
                    base_url=f"http://127.0.0.1:{server.server_port}/v1",
                    api_key=None,
                ))
                session.commit()
                error_type = None
                try:
                    asyncio.run(_payload(session, user.id))
                except Exception as exc:
                    # Error text might contain request data; print only type.
                    error_type = type(exc).__name__
            unsafe = any(observed)
            print(json.dumps({
                "probe": "SEC-01-model-discovery",
                "synthetic_credentials": True,
                "temporary_database": True,
                "external_model_calls": 0,
                "capture_requests": len(observed),
                "managed_key_received_at_user_endpoint": unsafe,
                "resolver_error_type": error_type,
                "result": "VULNERABLE" if unsafe else "NOT_OBSERVED",
                "scope": "model discovery only; not enterprise acceptance",
            }, indent=2))
            return 1 if unsafe else 0
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
