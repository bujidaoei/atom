"""Opt-in live HTTP boundary probe with a short-lived, revoked owner session.

Run inside the serving API container. The probe prints status codes only and
uses a deliberately invalid project body, so a failed origin gate cannot
create a project. No bearer token or proof is written to disk or stdout.
"""

import os
import re
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from sqlalchemy import func, select

from app.access_repository import AccessRepository
from app.config import get_settings
from app.console_auth import DURABLE_COOKIE, proof_for_new_session
from app.db import SessionLocal
from app.durable_credentials import DurableConsoleCredentials
from app.models import Project
from app.project_origins import ProjectOriginRepository


def _status(url: str, *, token: str, proof: str, origin: str,
            method: str = "GET") -> int:
    request = Request(
        url,
        data=b"{}" if method == "POST" else None,
        headers={
            "Cookie": f"{DURABLE_COOKIE}={token}",
            "X-Atom-Console-Proof": proof,
            "Origin": origin,
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        with urlopen(request, timeout=15) as response:
            response.read(4096)
            return response.status
    except HTTPError as error:
        error.read(4096)
        return error.code


def main() -> None:
    if os.environ.get("ATOM_LIVE_CROSS_PORT_PROBE") != "1":
        raise RuntimeError("explicit_live_cross_port_opt_in_required")
    first_id = os.environ.get("ATOM_LIVE_FIRST_PROJECT_ID", "")
    second_id = os.environ.get("ATOM_LIVE_SECOND_PROJECT_ID", "")
    api_path = os.environ.get("ATOM_LIVE_CONSOLE_API_PATH", "")
    if not first_id or not second_id or first_id == second_id:
        raise RuntimeError("two_distinct_projects_required")
    if re.fullmatch(r"/[a-z0-9/-]+/api", api_path) is None:
        raise RuntimeError("explicit_console_api_path_required")
    settings = get_settings()
    if (settings.environment != "production" or settings.session_mode != "durable"
            or not settings.console_proof_required or not settings.ip_public_enabled
            or not settings.console_origin or not settings.ip_preview_address
            or settings.ip_preview_first_port is None
            or settings.ip_preview_last_port is None):
        raise RuntimeError("live_production_boundary_required")

    origins = ProjectOriginRepository(
        settings.db_path, first_port=settings.ip_preview_first_port,
        last_port=settings.ip_preview_last_port,
    )
    pairs = [origins.for_project(project_id) for project_id in (first_id, second_id)]
    if any(pair is None for pair in pairs):
        raise RuntimeError("project_origin_missing")
    public_origins = [
        f"https://{settings.ip_preview_address}:{pair.public_port}"
        for pair in pairs
    ]
    if len(set(public_origins)) != 2:
        raise RuntimeError("public_origins_not_distinct")

    with SessionLocal() as db:
        projects = [db.get(Project, project_id) for project_id in (first_id, second_id)]
        if any(project is None for project in projects):
            raise RuntimeError("project_missing")
        if projects[0].user_id != projects[1].user_id:
            raise RuntimeError("project_owner_mismatch")
        owner_id = projects[0].user_id
        initial_count = db.scalar(select(func.count(Project.id)))

    repository = AccessRepository(settings.db_path)
    session = repository.create_console_session(user_id=owner_id, lifetime_seconds=120)
    try:
        codec = DurableConsoleCredentials(
            repository, key=settings.secret, issuer="atom-console",
            audience="atom-console",
        )
        token = codec.sign(user_id=owner_id, session_id=session.id)
        proof = proof_for_new_session(token)
        api = f"{settings.console_origin}{api_path}"
        me = _status(f"{api}/auth/me", token=token, proof=proof,
                     origin=settings.console_origin)
        same_origin = _status(f"{api}/projects", token=token, proof=proof,
                              origin=settings.console_origin, method="POST")
        cross_origin = [
            _status(f"{api}/projects", token=token, proof=proof,
                    origin=origin, method="POST")
            for origin in public_origins
        ]
        public_host = [
            _status(f"{origin}{api_path}/projects",
                    token=token, proof=proof, origin=origin, method="POST")
            for origin in public_origins
        ]
        with SessionLocal() as db:
            final_count = db.scalar(select(func.count(Project.id)))
        if (me != 200 or same_origin != 422 or cross_origin != [403, 403]
                or any(status not in (403, 404, 405) for status in public_host)
                or final_count != initial_count):
            raise AssertionError(
                f"live_boundary_failed: me={me} control={same_origin} "
                f"cross={cross_origin} public={public_host} "
                f"count_unchanged={final_count == initial_count}"
            )
        print("live_cross_port_denial_verified: control=422 cross=403/403 "
              f"public={public_host[0]}/{public_host[1]} project_count_unchanged=true")
    finally:
        repository.revoke_console_session(user_id=owner_id, session_id=session.id)


if __name__ == "__main__":
    main()
