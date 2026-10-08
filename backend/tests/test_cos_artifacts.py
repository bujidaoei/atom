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
from app.cos_artifact_worker import transfer
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


@pytest.mark.parametrize('code,expected', [
    ('InvalidAccessKeyId', 'artifact_credentials_invalid'),
    ('AccessDenied', 'artifact_access_denied'),
    ('SignatureDoesNotMatch', 'artifact_signature_invalid'),
])
def test_sdk_credentials_and_permissions_propagate_without_raw_error(monkeypatch, code, expected):
    import qcloud_cos
    from qcloud_cos.cos_exception import CosServiceError
    def denied(**_kwargs):
        raise CosServiceError('GET', {'code': code, 'message': 'signed-url-secret'}, 403)
    monkeypatch.setattr(qcloud_cos, 'CosS3Client', lambda *_a, **_k: SimpleNamespace(get_object=denied))
    with pytest.raises(ArtifactError) as failure:
        transfer({'region': 'ap-guangzhou', 'access_key': 'synthetic-access',
                  'secret_key': 'synthetic-secret', 'endpoint': 'https://cos.ap-guangzhou.myqcloud.com',
                  'bucket': 'test-1234567890', 'prefix': 'test/atom', 'key': 'a' * 64,
                  'operation': 'read'}, b'')
    assert str(failure.value) == expected


@pytest.mark.parametrize('code', ['artifact_credentials_invalid', 'artifact_access_denied', 'artifact_signature_invalid'])
def test_parent_preserves_only_allowlisted_worker_codes(monkeypatch, code):
    monkeypatch.setattr(subprocess, 'run', lambda *_a, **_k:
        SimpleNamespace(returncode=0, stdout=b'ERROR\n' + code.encode()))
    with pytest.raises(ArtifactError, match=code):
        CosArtifactStore(configuration()).read('a' * 64)
