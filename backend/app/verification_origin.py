"""Ephemeral loopback origin backed by one fully verified snapshot.

This is a building block for the isolated verifier, not an authority to
register results or publish a release. The caller must supervise its process.
"""
from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import mimetypes
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.parse import urlsplit

from .artifacts import Artifact
from .content_policy import validate_content_manifest, GENERATED_CONTENT_HEADERS
from .snapshots import receive_snapshot, verify_snapshot


class OriginError(ValueError):
    pass


def _files(payload: bytes, artifact: Artifact) -> dict[str, bytes]:
    if type(payload) is not bytes or type(artifact) is not Artifact:
        raise OriginError('invalid_verifier_artifact')
    if len(payload) != artifact.size or hashlib.sha256(payload).hexdigest() != artifact.key:
        raise OriginError('verifier_artifact_mismatch')
    verified = verify_snapshot(io.BytesIO(payload))
    if verified.revision != artifact.revision:
        raise OriginError('verifier_artifact_mismatch')
    validate_content_manifest(verified)
    with TemporaryDirectory(prefix='atom-verifier-') as parent:
        received = receive_snapshot(io.BytesIO(payload), Path(parent))
        if received.revision != artifact.revision or received.files != verified.files:
            raise OriginError('verifier_artifact_mismatch')
        # Freeze bytes before opening the socket. A mutable staging directory
        # cannot silently change the artifact served between browser checks.
        files = {}
        for entry in received.files:
            body = received.path.joinpath(*entry.path.split('/')).read_bytes()
            if len(body) != entry.size or hashlib.sha256(body).hexdigest() != entry.sha256:
                raise OriginError('verifier_artifact_mismatch')
            files['/' + entry.path] = body
    if '/index.html' not in files:
        raise OriginError('verifier_entry_missing')
    return files


@contextmanager
def pinned_snapshot_origin(payload: bytes, artifact: Artifact):
    """Serve only captured artifact bytes from an unadvertised loopback port."""
    files = _files(payload, artifact)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def _respond(self):
            expected_host = f'127.0.0.1:{self.server.server_port}'
            if self.headers.get_all('Host', []) != [expected_host]:
                self.send_error(404)
                return
            parsed = urlsplit(self.path)
            path = parsed.path
            if (parsed.scheme or parsed.netloc or parsed.query or parsed.fragment
                    or not path.startswith('/') or '\\' in path or '\0' in path
                    or any(part in ('.', '..') for part in path.split('/'))):
                self.send_error(404)
                return
            if path == '/' or path.endswith('/'):
                path += 'index.html'
            body = files.get(path)
            if body is None:
                self.send_error(404)
                return
            media = mimetypes.guess_type(path)[0] or 'application/octet-stream'
            self.send_response(200)
            self.send_header('Content-Type', media)
            self.send_header('Content-Length', str(len(body)))
            for name, value in GENERATED_CONTENT_HEADERS.items():
                self.send_header(name, value)
            self.end_headers()
            if self.command == 'GET':
                self.wfile.write(body)

        def do_GET(self):
            self._respond()

        def do_HEAD(self):
            self._respond()

        def do_POST(self):
            self.send_error(405)

    class OriginServer(ThreadingHTTPServer):
        daemon_threads = True

    server = OriginServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, name='atom-verifier-origin', daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        if thread.is_alive():
            raise OriginError('verifier_origin_shutdown_failed')
