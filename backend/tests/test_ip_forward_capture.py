"""Real schema18 backup/restore is gated by stopped IDs and maintenance bytes."""

import importlib.util
from pathlib import Path
import sqlite3
import sys

import pytest


DEPLOY = Path(__file__).resolve().parents[2] / 'deploy'
sys.path.insert(0, str(DEPLOY))
spec = importlib.util.spec_from_file_location('ip_forward_capture',
                                             DEPLOY / 'ip_forward_capture.py')
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def fixture(tmp_path):
    source = tmp_path / 'source'
    backup_root = tmp_path / 'backups'
    for path in (source, backup_root, source / 'data', source / 'broker',
                 source / 'caddy'):
        path.mkdir(mode=0o700)
    with sqlite3.connect(source / 'data' / 'atom.db') as db:
        db.executescript('''
            PRAGMA user_version=18;
            CREATE TABLE projects(id TEXT PRIMARY KEY, active_run_id TEXT);
            CREATE TABLE revision_attempts(state TEXT);
            CREATE TABLE revision_records(id TEXT PRIMARY KEY);
            CREATE TABLE revision_artifacts(key TEXT PRIMARY KEY);
            CREATE TABLE release_records(id TEXT PRIMARY KEY);
            CREATE TABLE release_publications(project_id TEXT PRIMARY KEY, release_id TEXT);
            CREATE TABLE release_rollback_sources(id TEXT PRIMARY KEY);
            CREATE TABLE project_origin_ports(project_id TEXT, purpose TEXT, port INTEGER);
            INSERT INTO projects VALUES ('one', NULL);
            INSERT INTO release_records VALUES ('release-one');
            INSERT INTO release_publications VALUES ('one', 'release-one');
            INSERT INTO project_origin_ports VALUES ('one', 'preview', 20000);
            INSERT INTO project_origin_ports VALUES ('one', 'public', 20001);
        ''')
    with sqlite3.connect(source / 'broker' / 'registry.db') as db:
        db.executescript('''
            PRAGMA user_version=3;
            CREATE TABLE attempts(id TEXT PRIMARY KEY, state TEXT);
        ''')
    publication = {'ATOM_PUBLIC_IP': '192.0.2.10',
                   'ATOM_ACME_DIRECTORY': 'https://acme.example.test/directory',
                   'ATOM_PREVIEW_UPSTREAM': 'preview:8000',
                   'ATOM_PUBLIC_UPSTREAM': 'public:8000',
                   'ATOM_FIRST_PORT': '20000', 'ATOM_LAST_PORT': '20003',
                   'ATOM_STORAGE_ENV_FILE': str(tmp_path / 'storage.env')}
    routes = (module.OriginRoute('one', 'preview', 20000),
              module.OriginRoute('one', 'public', 20001))
    base = module.ip_cutover_apply._maintenance_caddyfile(
        publication['ATOM_PUBLIC_IP'], publication['ATOM_ACME_DIRECTORY'])
    (source / 'caddy' / 'Caddyfile.base').write_bytes(base)
    rendered = module.render_ip_maintenance_routes(base.decode(), routes,
        module.IpIngressConfig(publication['ATOM_PUBLIC_IP'],
            publication['ATOM_PREVIEW_UPSTREAM'], publication['ATOM_PUBLIC_UPSTREAM'],
            publication['ATOM_ACME_DIRECTORY'])).encode()
    (source / 'caddy' / 'Caddyfile').write_bytes(rendered)
    config = module.protected_cutover.CutoverConfig(
        'atom-candidate', 'atom-candidate-broker', tmp_path / 'unused-data',
        tmp_path / 'unused-broker', backup_root, tmp_path / 'state',
        'isolated', 18080, 18, 3, Path('/usr/bin/docker'), Path('/var/run/docker.sock'))
    ids = {role: f'{number:064x}' for number, role in
           enumerate((*module.ip_forward_writers.STOP_ORDER, 'caddy'), start=1)}
    active = {'revision': 'a' * 40, 'candidateDirectory': str(source), 'containerIds': ids,
              'imageId': 'sha256:' + 'a' * 64,
              'successor': {'revision': 'f' * 40, 'imageId': 'sha256:' + 'b' * 64}}
    stopped = module.ip_forward_writers.StoppedWriters(
        {role: ids[role] for role in module.ip_forward_writers.STOP_ORDER})
    return source, config, publication, routes, active, stopped


def patches(monkeypatch, source, active):
    monkeypatch.setattr(module, '_private_path', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module.ip_forward_writers, '_identity',
                        lambda *_args, **_kwargs: {'State': {'Running': False}})
    monkeypatch.setattr(module.protected_cutover, '_inspect',
                        lambda *_args: {'Id': active['containerIds']['caddy'],
                            'State': {'Running': True},
                            'Mounts': [{'Destination': '/etc/caddy',
                                        'Source': str(source / 'caddy'),
                                        'Type': 'bind', 'RW': False}]})
    monkeypatch.setattr(module.ip_cutover_apply, '_maintenance_probe',
                        lambda *_args: None)
    monkeypatch.setattr(module, 'probe_ip_maintenance_routes',
                        lambda *_args: None)
    monkeypatch.setattr(module, '_verify_cos', lambda **_kwargs: 'c' * 64)


def test_real_schema18_pair_only_after_maintenance_and_stopped_ids(tmp_path, monkeypatch):
    source, config, publication, routes, active, stopped = fixture(tmp_path)
    patches(monkeypatch, source, active)
    receipt = module.capture(config=config, active=active, publication=publication,
        stopped=stopped, routes=routes, successor_revision='f' * 40)
    assert receipt.artifact_count == 0 and receipt.origin_count == 2
    assert receipt.cos_inventory_sha256 == 'c' * 64
    assert receipt.caddy_sha256 == module.hashlib.sha256(
        (source / 'caddy' / 'Caddyfile').read_bytes()).hexdigest()
    assert module.paired_backup.verify(receipt.backup) == \
        module.paired_backup.verify(receipt.candidate)
    with sqlite3.connect(receipt.candidate / 'data' / 'atom.db') as db:
        assert db.execute('SELECT release_id FROM release_publications').fetchone() == (
            'release-one',)
    assert (source / 'caddy' / 'Caddyfile').read_bytes() == \
        (receipt.candidate / 'Caddyfile').read_bytes()


@pytest.mark.parametrize('fault', ['writer', 'maintenance', 'origin'])
def test_refuses_capture_before_backup_on_failed_exclusion(tmp_path, monkeypatch, fault):
    source, config, publication, routes, active, stopped = fixture(tmp_path)
    patches(monkeypatch, source, active)
    if fault == 'writer':
        def running(*_args, **_kwargs):
            raise module.ip_forward_writers.WriterError('writer_identity_changed')
        monkeypatch.setattr(module.ip_forward_writers, '_identity', running)
    elif fault == 'maintenance':
        (source / 'caddy' / 'Caddyfile').write_bytes(b'old normal route')
    else:
        with sqlite3.connect(source / 'data' / 'atom.db') as db:
            db.execute("UPDATE project_origin_ports SET port=20002 WHERE purpose='public'")
            db.commit()
    with pytest.raises((module.CaptureError, module.ip_forward_writers.WriterError)):
        module.capture(config=config, active=active, publication=publication,
            stopped=stopped, routes=routes, successor_revision='f' * 40)
    assert not any(config.backup_root.iterdir())


def test_cos_verifier_uses_read_only_candidate_and_rejects_count_mismatch(
        tmp_path, monkeypatch):
    source, config, publication, _routes, _active, _stopped = fixture(tmp_path)
    monkeypatch.setattr(module, '_private_path', lambda *_args, **_kwargs: None)
    observed = []
    def command(args, *, timeout):
        observed.append((args, timeout))
        return {'schema_version': 18, 'artifact_count': 0,
                'artifact_bytes': 0, 'inventory_sha256': 'd' * 64}
    monkeypatch.setattr(module.ip_cutover_apply, '_json_command', command)
    image = 'sha256:' + 'b' * 64
    assert module._verify_cos(config=config, candidate=source, image_id=image,
        storage_env=Path(publication['ATOM_STORAGE_ENV_FILE']), artifacts=0) == 'd' * 64
    args, timeout = observed[0]
    assert timeout == 600 and '--read-only' in args and '--verify-only' in args
    assert f'{source / "data"}:/data:ro' in args and image in args
    assert 'put' not in args
    with pytest.raises(module.CaptureError, match='forward_cos_receipt_mismatch'):
        module._verify_cos(config=config, candidate=source, image_id=image,
            storage_env=Path(publication['ATOM_STORAGE_ENV_FILE']), artifacts=1)
