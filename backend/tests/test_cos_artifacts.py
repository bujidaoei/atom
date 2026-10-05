"""COS boundary faults; synthetic credentials, no external network calls."""
import io
import json
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from app.artifacts import ArtifactError
from app.cos_artifacts import CosArtifactStore
from app.cos_artifact_worker import _read
from app.snapshots import MAX_ARCHIVE_BYTES
from test_cos_configuration import configuration
from test_adoption_repository import snapshot


def test_worker_protocol_excludes_credentials_from_argv_environment_and_diagnostics(monkeypatch):
    payload, artifact = snapshot(b'<html>Verified bytes</html>')
    observed = []

    def execute(args, **kwargs):
        header, body = kwargs['input'].split(b'\n', 1)
        control = json.loads(header)
        assert control['secret_key'] == 'synthetic-secret-value'
        assert 'synthetic-secret-value' not in repr(args)
        assert not any(name.startswith('ATOM_') for name in kwargs['env'])
        assert kwargs['timeout'] == 45 and kwargs['stderr'] == subprocess.DEVNULL
        observed.append((control['operation'], body))
        return SimpleNamespace(returncode=0, stdout=b'OK\n' + payload)

    monkeypatch.setattr(subprocess, 'run', execute)
    store = CosArtifactStore(configuration())
    assert store.put(payload) == artifact
    assert store.read(artifact.key) == payload
    assert observed == [('put', payload), ('read', b'')]


def test_real_stalled_worker_is_killed_and_capacity_released(monkeypatch):
    run = subprocess.run
    def stalled(_args, **kwargs):
        return run([sys.executable, '-c', 'import time; time.sleep(30)'], **kwargs)
    monkeypatch.setattr(subprocess, 'run', stalled)
    started = time.monotonic()
    with pytest.raises(ArtifactError, match='artifact_transport_timeout'):
        CosArtifactStore(configuration(), operation_seconds=1).read('a' * 64)
    assert time.monotonic() - started < 6
    monkeypatch.setattr(subprocess, 'run', lambda *_args, **_kwargs:
                        SimpleNamespace(returncode=0, stdout=b'ERROR\nartifact_not_found'))
    with pytest.raises(ArtifactError, match='artifact_not_found'):
        CosArtifactStore(configuration()).read('a' * 64)


@pytest.mark.parametrize('output', [b'OK\ncorrupt', b'ERROR\nsecret:do-not-display', b'unexpected'])
def test_untrusted_worker_output_never_becomes_artifact_or_error_text(monkeypatch, output):
    monkeypatch.setattr(subprocess, 'run', lambda *_args, **_kwargs:
                        SimpleNamespace(returncode=0, stdout=output))
    with pytest.raises(ArtifactError) as error:
        CosArtifactStore(configuration()).read('a' * 64)
    assert 'do-not-display' not in str(error.value)


@pytest.mark.parametrize('declared,payload', [(MAX_ARCHIVE_BYTES + 1, b''), (30, b'truncated')])
def test_remote_size_errors_close_response(declared, payload):
    raw = io.BytesIO(payload)
    client = SimpleNamespace(get_object=lambda **_kwargs: {
        'Content-Length': str(declared), 'Body': SimpleNamespace(get_raw_stream=lambda: raw)})
    with pytest.raises(ArtifactError, match='invalid_artifact'):
        _read(client, 'bucket', 'key')
    assert raw.closed
