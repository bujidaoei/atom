"""Validate the fixed Docker boundary and require an actual write receipt."""
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'deploy'))
import artifact_preflight


def configured(tmp_path, monkeypatch, **overrides):
    source = tmp_path / 'source'
    (source / 'data').mkdir(parents=True)
    with sqlite3.connect(source / 'data' / 'atom.db') as db:
        db.execute('PRAGMA user_version=19')
    observed = []
    result = dict(ok=True, write_readback=True, schema_version=19,
                  artifact_count=77, artifact_bytes=1234, probe_key='a' * 64,
                  inventory_sha256='b' * 64)
    result.update(overrides)
    monkeypatch.setattr(artifact_preflight.ip_forward_capture, '_private_path', lambda *_a, **_k: None)
    def execute(args, **kwargs):
        observed.append((args, kwargs))
        return result
    monkeypatch.setattr(artifact_preflight.ip_cutover_apply, '_json_command', execute)
    values = dict(config=SimpleNamespace(docker=Path('/usr/bin/docker')), source=source,
        image='sha256:' + 'c' * 64, storage_env=tmp_path / 'private.env')
    return values, observed


def test_private_fixed_process_no_credentials_in_command(tmp_path, monkeypatch):
    values, observed = configured(tmp_path, monkeypatch)
    assert artifact_preflight.verify(**values)['write_readback'] is True
    args, options = observed[0]
    assert args[args.index('--env-file') + 1] == str(values['storage_env'])
    assert '--read-only' in args and '--cap-drop' in args
    assert args[args.index('--volume') + 1].endswith(':/data:ro')
    assert args[-4:] == ['-m', 'app.storage_preflight', '--database', '/data/atom.db']
    assert options == {'timeout': 600}


@pytest.mark.parametrize('changes', [dict(write_readback=False), dict(ok=1),
    dict(schema_version=18), dict(probe_key='signed-url-secret'),
    dict(artifact_count=True), dict(inventory_sha256='invalid')])
def test_incomplete_or_untrusted_receipt_refuses_cutover(tmp_path, monkeypatch, changes):
    values, _ = configured(tmp_path, monkeypatch, **changes)
    with pytest.raises(artifact_preflight.ArtifactPreflightError, match='storage_preflight_receipt_mismatch'):
        artifact_preflight.verify(**values)
