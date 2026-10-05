"""One opt-in, authenticated real release write in the exposed successor API.

The host drill sends this source to the exact candidate API container over
``docker exec -i``. Only non-secret release identity is printed. The short
console session is revoked even if publication fails.
"""

import json
import os
import re
import sqlite3
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.access_repository import AccessRepository
from app.config import get_settings
from app.console_auth import DURABLE_COOKIE, proof_for_new_session
from app.durable_credentials import DurableConsoleCredentials
from app.release_repository import ReleaseRepository


def main() -> None:
    if os.environ.get("ATOM_LIVE_FORWARD_RELEASE_WRITE") != "1":
        raise RuntimeError("explicit_live_forward_release_write_opt_in_required")
    project_id = os.environ.get("ATOM_LIVE_FORWARD_PROJECT_ID", "")
    if re.fullmatch(r"[0-9a-f]{32}", project_id) is None:
        raise RuntimeError("explicit_existing_project_required")
    settings = get_settings()
    if (settings.environment != "production" or settings.session_mode != "durable"
            or not settings.console_proof_required or not settings.ip_public_enabled
            or settings.publication_verification != "advisory"
            or not settings.console_origin):
        raise RuntimeError("live_advisory_publication_boundary_required")
    with sqlite3.connect(settings.db_path.as_uri() + "?mode=ro", uri=True) as db:
        row = db.execute("""SELECT p.user_id,w.current_revision_id,r.generation,r.slug
            FROM projects p JOIN revision_workspaces w ON w.project_id=p.id AND w.heat_id IS NULL
            JOIN release_publications r ON r.project_id=p.id
            WHERE p.id=? AND p.active_run_id IS NULL AND w.active_attempt_id IS NULL
              AND r.live=1""", (project_id,)).fetchone()
    if row is None or any(value is None for value in row):
        raise RuntimeError("stable_published_project_required")
    owner, revision, generation, slug = row
    release_id = uuid.uuid4().hex
    payload = json.dumps({
        "releaseId": release_id, "expectedRevision": revision,
        "expectedGeneration": generation, "audience": "public", "slug": slug,
    }, separators=(",", ":")).encode("utf-8")
    repository = AccessRepository(settings.db_path)
    session = repository.create_console_session(user_id=owner, lifetime_seconds=120)
    try:
        credentials = DurableConsoleCredentials(
            repository, key=settings.secret, issuer="atom-console", audience="atom-console")
        token = credentials.sign(user_id=owner, session_id=session.id)
        proof = proof_for_new_session(token)
        request = Request(
            f"{settings.console_origin}/atom/api/projects/{project_id}/releases",
            data=payload, method="POST", headers={
                "Cookie": f"{DURABLE_COOKIE}={token}",
                "X-Atom-Console-Proof": proof,
                "X-Atom-Intent": "publish-verified-release",
                "Origin": settings.console_origin,
                "Content-Type": "application/json",
            })
        try:
            with urlopen(request, timeout=30) as response:
                status = response.status
                result = json.load(response)
        except HTTPError as error:
            error.close()
            raise RuntimeError(f"real_release_http_{error.code}") from None
        except URLError:
            raise RuntimeError("real_release_transport_unavailable") from None
        if (status != 200 or result.get("releaseId") != release_id
                or result.get("revisionId") != revision
                or result.get("generation") != generation + 1):
            raise RuntimeError("real_release_receipt_mismatch")
        current = ReleaseRepository(settings.db_path, required_schema="verified").current(
            owner=owner, project_id=project_id)
        if (current is None or current.release_id != release_id
                or current.revision_id != revision or current.generation != generation + 1):
            raise RuntimeError("real_release_pointer_mismatch")
        print(json.dumps({"releaseId": release_id, "revisionId": revision,
                          "generation": generation + 1}, sort_keys=True))
    finally:
        repository.revoke_console_session(user_id=owner, session_id=session.id)


if __name__ == "__main__":
    main()
