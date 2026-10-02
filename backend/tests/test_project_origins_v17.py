"""Real SQLite migration and immutable port ledger constraints."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.migrations import MigrationError, migrate, verify, verify_backup
from app.access_repository import AccessRepository
from app.content_repository import ContentRepository
from app.content_service import ContentService
from app.content_hosts import ContentHostError
from app.content_entry import ContentStartupError, IpPublicContentConfig, create_ip_public_app
from app.models import Project
from app.project_origins import OriginRoute, ProjectOriginError, ProjectOriginRepository
from app.project_public_hosts import ProjectPublicHosts
from app.ip_ingress import IngressError, IpIngressConfig, render_ip_caddyfile, render_ip_routes
from app.release_history import publication_history
from app.release_repository import ReleaseRepository
from app.revisions import RevisionRepository
from app.verification_repository import VerificationError, VerificationRepository
from test_revision_migrations import legacy
from test_publication_policy_v16 import v15_history
from test_rollback_v14_repository import historical
from test_v13_content_consumers import published
from test_verifier_authority import authorized
from test_adoption_verification_repository import adopted
from test_adoption_repository import prepared


@pytest.fixture
def v16(legacy, tmp_path):
    path, _ = legacy
    for version in (11, 12, 13, 14, 15, 16):
        migrate(path, tmp_path / f'before-v{version}.db', target_version=version)
    assert verify(path) == 16
    return path


def test_v17_port_ledger_is_immutable_and_never_reused(v16, tmp_path):
    path = v16
    backup = tmp_path / 'before-v17.db'
    result = migrate(path, backup, target_version=17)
    assert result.applied and result.version == verify(path) == 17
    assert result.backup_sha256 == verify_backup(backup, expected_version=16)
    assert not migrate(path, backup, target_version=17).applied
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO project_origin_ports VALUES ('project','preview',20000,1)")
        db.execute("INSERT INTO project_origin_ports VALUES ('project','public',20001,1)")
        for statement in (
            "INSERT INTO project_origin_ports VALUES ('project','preview',20002,1)",
            "INSERT INTO project_origin_ports VALUES ('missing','preview',20003,1)",
            "INSERT INTO project_origin_ports VALUES ('other','public',20001,1)",
            "INSERT INTO project_origin_ports VALUES ('project','public',80,1)",
            "UPDATE project_origin_ports SET port=20004 WHERE port=20000",
            "DELETE FROM project_origin_ports WHERE port=20000",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(statement)
        assert db.execute('SELECT purpose,port FROM project_origin_ports ORDER BY purpose').fetchall() == [
            ('preview', 20000), ('public', 20001)]
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []


def test_v17_failed_migration_keeps_exact_v16(v16, tmp_path, monkeypatch):
    from app.migrations import project_origins_v17
    real_apply = project_origins_v17.apply

    def fail(db):
        real_apply(db)
        raise sqlite3.OperationalError('injected before commit')

    monkeypatch.setattr(project_origins_v17, 'apply', fail)
    backup = tmp_path / 'failed-v17.db'
    with pytest.raises(MigrationError, match='migration_failed'):
        migrate(v16, backup, target_version=17)
    assert verify(v16) == 16
    assert verify_backup(backup, expected_version=16)


def test_ip_public_process_refuses_unmigrated_or_invalid_configuration(v16, tmp_path):
    config = IpPublicContentConfig(v16, tmp_path / 'artifacts',
                                   '192.0.2.10', 20000, 20003)
    with pytest.raises(ContentStartupError, match='public_startup_unavailable'):
        create_ip_public_app(config)
    with pytest.raises(ContentStartupError, match='public_configuration_invalid'):
        create_ip_public_app(IpPublicContentConfig(Path('relative.db'),
                                                  tmp_path / 'artifacts',
                                                  '192.0.2.10', 20000, 20003))


def test_origin_reservation_is_atomic_stable_and_bounded(v16, tmp_path):
    migrate(v16, tmp_path / 'before-origins.db', target_version=17)
    repository = ProjectOriginRepository(v16, first_port=20000, last_port=20003)
    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(repository.reserve, ['project'] * 8))
    assert all(item == outcomes[0] for item in outcomes)
    assert (outcomes[0].preview_port, outcomes[0].public_port) == (20000, 20001)
    assert repository.route(20000).purpose == 'preview'
    assert repository.route(20001).purpose == 'public'
    assert repository.route(20002) is None
    assert len(repository.active_routes()) == 2
    ingress = IpIngressConfig('192.0.2.10', 'atom-preview:8000', 'atom-public:8000',
                              'https://acme.example.test/directory')
    base = 'https://192.0.2.10 {\n  respond "console"\n}\n'
    rendered = render_ip_caddyfile(base, repository, ingress)
    assert rendered.count('https://192.0.2.10:20000 {') == 1
    assert rendered.count('https://192.0.2.10:20001 {') == 1
    assert 'reverse_proxy atom-preview:8000' in rendered
    assert 'reverse_proxy atom-public:8000' in rendered
    assert render_ip_caddyfile(base, repository, ingress) == rendered
    with pytest.raises(IngressError, match='invalid_base_caddyfile'):
        render_ip_caddyfile(rendered, repository, ingress)
    with pytest.raises(IngressError, match='invalid_ingress_upstream'):
        IpIngressConfig('192.0.2.10', 'atom-preview:8000\nrespond "unsafe"',
                        'atom-public:8000', 'https://acme.example.test/directory')
    with pytest.raises(IngressError, match='invalid_acme_directory'):
        IpIngressConfig('192.0.2.10', 'atom-preview:8000', 'atom-public:8000',
                        'https://acme.example.test:bad/directory')
    with pytest.raises(IngressError, match='invalid_origin_route'):
        render_ip_routes(base, (OriginRoute('project', 'preview', 20000),
                                OriginRoute('other', 'public', 20000)), ingress)
    with pytest.raises(ProjectOriginError, match='origin_range_changed'):
        ProjectOriginRepository(v16, first_port=20002, last_port=20005)

    engine = create_engine('sqlite:///' + v16.as_posix())
    with Session(engine) as session:
        session.add(Project(id='other', user_id='user', prompt='another site', title='Other'))
        session.add(Project(id='third', user_id='user', prompt='third site', title='Third'))
        session.commit()
    engine.dispose()
    assert repository.reserve('other').preview_port == 20002
    with pytest.raises(ProjectOriginError, match='origin_capacity'):
        repository.reserve('third')
    with sqlite3.connect(v16) as db:
        assert db.execute("SELECT count(*) FROM project_origin_ports WHERE project_id='third'").fetchone() == (0,)
        db.execute('PRAGMA foreign_keys=ON')
        db.execute("DELETE FROM projects WHERE id='other'")
        assert db.execute('SELECT count(*) FROM project_origin_ports').fetchone() == (4,)
        with pytest.raises(sqlite3.IntegrityError, match='reserved_project_identity'):
            db.execute("INSERT INTO projects (id,user_id,prompt,title) VALUES ('other','user','reuse','Reuse')")
    assert repository.route(20002) is None
    assert len(repository.active_routes()) == 2
    retired = render_ip_caddyfile(base, repository, ingress)
    assert 'https://192.0.2.10:20002 {' not in retired
    assert 'https://192.0.2.10:20000 {' in retired


def test_existing_project_port_migration_is_all_or_nothing(v16, tmp_path):
    migrate(v16, tmp_path / 'before-existing-origins.db', target_version=17)
    engine = create_engine('sqlite:///' + v16.as_posix())
    with Session(engine) as session:
        session.add_all([Project(id=identity, user_id='user', prompt=identity, title=identity)
                         for identity in ('other', 'third')])
        session.commit()
    engine.dispose()
    short = ProjectOriginRepository(v16, first_port=20000, last_port=20003)
    with pytest.raises(ProjectOriginError, match='origin_capacity'):
        short.reserve_existing()
    with sqlite3.connect(v16) as db:
        assert db.execute('SELECT count(*) FROM project_origin_ports').fetchone() == (0,)
    enough = ProjectOriginRepository(v16, first_port=20000, last_port=20005)
    assigned = enough.reserve_existing()
    assert [(item.project_id, item.preview_port, item.public_port) for item in assigned] == [
        ('other', 20000, 20001), ('project', 20002, 20003), ('third', 20004, 20005)]
    assert enough.reserve_existing() == assigned
    with sqlite3.connect(v16) as db:
        assert db.execute('SELECT count(*) FROM project_origin_ports').fetchone() == (6,)
        db.execute('PRAGMA foreign_keys=ON')
        db.execute("DELETE FROM projects WHERE id='other'")
    assert [(item.project_id, item.preview_port) for item in enough.reserve_existing()] == [
        ('project', 20002), ('third', 20004)]
    assert enough.route(20000) is None
    expanded = ProjectOriginRepository(v16, first_port=20000, last_port=20007)
    engine = create_engine('sqlite:///' + v16.as_posix())
    with Session(engine) as session:
        session.add(Project(id='fourth', user_id='user', prompt='fourth', title='Fourth'))
        session.flush()
        ports = expanded.reserve_in_transaction(
            session.connection().connection.driver_connection, 'fourth')
        assert (ports.preview_port, ports.public_port) == (20006, 20007)
        session.commit()
    with Session(engine) as session:
        session.add(Project(id='fifth', user_id='user', prompt='fifth', title='Fifth'))
        session.flush()
        with pytest.raises(ProjectOriginError, match='origin_capacity'):
            expanded.reserve_in_transaction(
                session.connection().connection.driver_connection, 'fifth')
        session.rollback()
    with Session(engine) as session:
        assert session.get(Project, 'fifth') is None
    engine.dispose()
    assert expanded.for_project('fourth') == ports


def test_v17_preserves_existing_release_and_session_consumers(v15_history, tmp_path):
    path = v15_history
    migrate(path, tmp_path / 'before-policy-v16.db', target_version=16)
    migrate(path, tmp_path / 'before-origins-v17.db', target_version=17)
    with sqlite3.connect(path) as db:
        owner, project_id, slug = db.execute('''SELECT r.creator_id,p.project_id,p.slug
            FROM release_publications p JOIN release_records r ON r.id=p.release_id''').fetchone()
    release = ReleaseRepository(path, required_schema=16)
    current = release.current(owner=owner, project_id=project_id)
    assert current is not None and current.slug == slug and current.verification_mode == 'required'
    assert publication_history(path, owner=owner, project_id=project_id)['items']
    assert release.resolve(slug=slug, viewer=owner).release_id == current.release_id
    assert ContentRepository(path).resolve(binding_id=current.binding_id, viewer=owner).release_id == current.release_id
    assert RevisionRepository(path).path == path
    assert VerificationRepository(path).path == path
    session = AccessRepository(path).create_console_session(user_id=owner, lifetime_seconds=60)
    assert AccessRepository(path).console_session(user_id=owner, session_id=session.id) == session


def test_v17_direct_publication_uses_saved_artifact_without_required_check(v15_history, historical, tmp_path):
    path, store, intent, _source, _displaced = historical
    assert path == v15_history
    migrate(path, tmp_path / 'before-policy-v16.db', target_version=16)
    migrate(path, tmp_path / 'before-origins-v17.db', target_version=17)
    repository = ReleaseRepository(path, required_schema=16)
    request = {key: value for key, value in intent.items()
               if key not in ('verification_id', 'policy_digest', 'runner_version')}
    request.update(release_id='a' * 32, expected_generation=3)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE requirements SET checks_json='not valid json'")
    published = repository.publish_snapshot(store, **request)
    assert published.generation == 4
    assert repository.publish_snapshot(store, **request) == published
    current = repository.current(owner='user', project_id='project')
    assert current.release_id == published.release_id
    assert current.verification_mode == 'advisory'
    assert repository.resolve(slug=published.slug).revision_id == request['expected_revision']
    content = ContentRepository(path)
    binding = content.public_project_binding(project_id='project')
    assert binding.release_id == published.release_id
    assert content.resolve(binding_id=binding.id).release_id == published.release_id
    origins = ProjectOriginRepository(path, first_port=20000, last_port=20003)
    assert origins.reserve('project').public_port == 20001
    hosts = ProjectPublicHosts('192.0.2.10', origins, content)
    with TestClient(ContentService(content, store, hosts),
                    base_url='https://192.0.2.10:20001') as client:
        page = client.get('/')
        assert page.status_code == 200 and page.content == b'<html>heat</html>'
        assert page.headers['x-atom-release'] == published.release_id
        assert client.get('https://192.0.2.10:20000/').status_code == 404
        assert client.get('https://192.0.2.10:20002/').status_code == 404
        assert client.get('https://192.0.2.10:20001/_atom/exchange').status_code == 404
        with pytest.raises(ContentHostError, match='invalid_content_host'):
            hosts.route([(b'host', b'192.0.2.10:20001'),
                         (b'host', b'192.0.2.10:20001')])
        with pytest.raises(ContentHostError, match='invalid_content_host'):
            hosts.route([(b'host', b'192.0.2.10:020001')])
        with pytest.raises(ContentHostError, match='invalid_content_host'):
            hosts.route([(b'host', b'192.0.2.11:20001')])
        with pytest.raises(ContentHostError, match='invalid_public_address'):
            ProjectPublicHosts('192.000.2.10', origins, content)
    repository.unpublish(owner='user', project_id='project', command_id='b' * 32,
                         expected_release=published.release_id, expected_generation=4)
    with pytest.raises(VerificationError, match='content_not_found'):
        content.public_project_binding(project_id='project')
    with TestClient(ContentService(content, store, hosts),
                    base_url='https://192.0.2.10:20001') as client:
        assert client.get('/').status_code == 404
