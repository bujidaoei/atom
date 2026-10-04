"""Scoped views cannot change version when another preview is opened."""
import sqlite3

import pytest
from starlette.testclient import TestClient

from app.access_repository import AccessRepository
from app.migrations import migrate
from app.preview_access import PreviewAccessError, PreviewAccessRepository
from app.preview_service import PreviewService
from app.project_origins import ProjectOriginRepository
from app.project_port_hosts import ProjectPortHosts
from test_adoption_repository import prepared
from test_adoption_verification_repository import adopted
from test_revision_migrations import legacy
from test_rollback_v14_repository import historical
from test_v13_content_consumers import published
from test_verifier_authority import authorized


@pytest.fixture
def views(historical, tmp_path):
    path, store, *_ = historical
    for version in range(15, 19):
        migrate(path, tmp_path / f'view-v{version}.db', target_version=version)
    origins = ProjectOriginRepository(path, first_port=20000, last_port=20003)
    origins.reserve('project')
    source = AccessRepository(path).create_console_session(user_id='user', lifetime_seconds=900)
    with sqlite3.connect(path) as db:
        revision = db.execute('SELECT revision_id FROM release_records LIMIT 1').fetchone()[0]
    access = PreviewAccessRepository(path)
    request = dict(owner_id='user', source_session_id=source.id,
                   project_id='project', revision_id=revision)
    return access, store, ProjectPortHosts('192.0.2.10', origins), request


def test_scoped_views_coexist_and_selector_alone_grants_nothing(views):
    access, store, hosts, request = views
    first, second = access.issue(**request), access.issue(**request)
    with TestClient(PreviewService(access, store, hosts), base_url=hosts.origin(20000)) as client:
        paths = []
        for grant in (first, second):
            response = client.post('/_atom/exchange', content=grant.secret,
                headers={'Origin': hosts.origin(20000), 'Content-Type': 'application/octet-stream'})
            assert response.status_code == 200
            body = response.json()
            assert body['viewId'] == grant.view_id
            assert f'Path={body["path"]}' in response.headers['set-cookie']
            paths.append(body['path'])
        assert paths[0] != paths[1]
        for path in paths * 2:
            response = client.get(path)
            assert response.status_code == 200 and response.content == b'<html>heat</html>'
            assert response.headers['referrer-policy'] == 'same-origin'
            assert "frame-ancestors https://192.0.2.10;" in response.headers['content-security-policy']
        assert client.get('/').status_code == 404
        routed = client.get('/index.html', headers={'Referer': hosts.origin(20000) + paths[0]},
                            follow_redirects=False)
        assert routed.status_code == 307 and routed.headers['location'] == paths[0] + 'index.html'
        assert client.get(routed.headers['location']).status_code == 200
        assert client.get('/index.html', headers={'Referer': 'https://evil.example/' + paths[0]}).status_code == 404
        assert client.get(paths[0] + '_atom/resume').status_code == 200
        client.cookies.clear()
        assert client.get(paths[0]).status_code == 404


def test_replacement_is_source_bound_and_does_not_revoke_other_view(views):
    access, _store, _hosts, request = views
    first, second = access.issue(**request), access.issue(**request)
    a = access.exchange(project_id='project', handoff=first.secret)
    b = access.exchange(project_id='project', handoff=second.secret)
    with pytest.raises(PreviewAccessError):
        access.authorize(project_id='project', session_secret=a.secret, view_id=second.view_id)
    access.issue(**request, replace_view_id=first.view_id)
    with pytest.raises(PreviewAccessError):
        access.authorize(project_id='project', session_secret=a.secret, view_id=first.view_id)
    assert access.authorize(project_id='project', session_secret=b.secret,
                            view_id=second.view_id).revision_id == request['revision_id']


def test_two_distinct_revisions_keep_all_resource_bytes_and_reject_invalid_paths(views):
    import hashlib
    import json
    import struct
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.artifacts import Artifact
    from app.models import RaceHeat
    from app.revisions import RevisionRepository

    access, store, hosts, request = views
    # A second real workspace head, with an independently validated snapshot.
    engine = create_engine('sqlite:///' + str(access.path))
    with Session(engine) as db:
        db.add(RaceHeat(id='second-heat', race_id='race', model='test'))
        db.commit()
    engine.dispose()
    files = {'app.js': b'window.version = 2;', 'index.html': b'<script src="/app.js"></script>version two',
             'styles.css': b'body{color:rgb(1,2,3)}', 'nested/module.js': b'export default 2;',
             'icon.svg': b'<svg xmlns="http://www.w3.org/2000/svg" width="2" height="2"/>'}
    manifest = json.dumps({'version': 1, 'files': [dict(path=path, size=len(data),
        sha256=hashlib.sha256(data).hexdigest()) for path, data in sorted(files.items())]},
        sort_keys=True, separators=(',', ':')).encode()
    payload = b'ATOMSNAP1\n' + struct.pack('>I', len(manifest)) + manifest + b''.join(files[k] for k in sorted(files))
    artifact = Artifact(hashlib.sha256(payload).hexdigest(), hashlib.sha256(manifest).hexdigest(), len(payload))
    revisions = RevisionRepository(access.path)
    workspace = revisions.ensure_workspace('user', 'project', 'second-heat')
    revision = revisions.bootstrap('user', workspace, artifact)
    class Versions:
        def read(self, key):
            return payload if key == artifact.key else store.read(key)
    first = access.issue(**request)
    second = access.issue(**{**request, 'revision_id': revision})
    with TestClient(PreviewService(access, Versions(), hosts), base_url=hosts.origin(20000)) as client:
        paths = []
        for grant in (first, second):
            response = client.post('/_atom/exchange', content=grant.secret,
                headers={'Origin': hosts.origin(20000), 'Content-Type': 'application/octet-stream'})
            assert response.status_code == 200
            paths.append(response.json()['path'])
        for _ in range(3):
            assert client.get(paths[0]).content == b'<html>heat</html>'
            assert client.get(paths[1]).content == files['index.html']
            for name, content in files.items():
                assert client.get(paths[1] + name).content == content
                assert client.get('/' + name, headers={'Referer': hosts.origin(20000) + paths[1]}).content == content
            assert client.get('/app.js', headers={'Referer': hosts.origin(20000) + paths[1]}).content == files['app.js']
            assert client.get(paths[0] + 'app.js').status_code == 404
        for tail in ('%2e%2e/app.js', '%252e%252e/app.js', '%2fapp.js', '%5capp.js'):
            assert client.get(paths[1] + tail).status_code == 404
