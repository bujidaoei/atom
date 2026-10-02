"""Real Docker report enters v13 only through the trusted supervised path."""
import asyncio
import json
import multiprocessing
import os
from pathlib import Path
import secrets
import signal
import socket
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
import time

import pytest
import httpx

from app.migrations import migrate
from app.artifacts import ArtifactStore
from app.content_repository import ContentRepository
from app.content_entry import ContentProcessConfig, create_app as create_content_app
from app.release_repository import ReleaseRepository
from app.release_view import materialized_content
from app.verification_contract import capture_contract
from app.verification_repository import VerificationRepository
from app.verification_repository import VerificationError
from app.verifier_authority import VerifierAuthority
from app.verifier_supervisor import SupervisorError, VerifierSupervisor
from app.verifier_coordinator import VerifierCoordinator
from app.verifier_service import (VerifierProcessConfig, VerifierStartupError,
                                  create_app as create_verifier_app)
from app.verifier_client import VerifierClient, VerifierClientError, VerifierObservation
from app.sandbox.daemon_lease import DaemonLeaseError
from test_adoption_repository import Store, prepared, snapshot
from test_adoption_verification_repository import adopted
from test_revision_migrations import legacy


IMAGE = os.environ.get('ATOM_VERIFIER_TEST_IMAGE_DIGEST')
pytestmark = pytest.mark.skipif(not IMAGE, reason='requires pinned local Docker verifier image')
PROFILE = Path(__file__).resolve().parents[3] / 'deploy' / 'verifier-seccomp.json'


@pytest.fixture
def assignment(adopted, tmp_path, request):
    path, receipt, intent = adopted
    checks = ([{'type': 'flow', 'selector': '#missing', 'expect': 'body'}]
              if getattr(request, 'param', None) == 'slow' else
              [{'type': 'exists', 'selector': 'body'}])
    requirement = {'key': 'page', 'title': 'Page', 'detail': '',
                   'checks': checks}
    with sqlite3.connect(path) as db:
        db.execute('UPDATE requirements SET checks_json=? WHERE project_id=?',
                   (json.dumps(requirement['checks']), 'project'))
    intent['expected_contract'] = capture_contract([requirement]).digest
    migrate(path, tmp_path / 'before-v13.db', target_version=13)
    if getattr(request, 'param', None) == 'v14':
        migrate(path, tmp_path / 'before-v14.db', target_version=14)
    request = VerificationRepository(path).reserve(**intent)
    authority = VerifierAuthority(path)
    supervisor = VerifierSupervisor(image=IMAGE, seccomp_path=PROFILE, verifier_id='worker-1')
    dispatched = authority.dispatch(owner='user', request_id=request.id,
        artifact=receipt.artifact, route_id='a' * 32, verifier_id='worker-1',
        environment_digest=supervisor.environment_digest)
    payload, artifact = snapshot(b'<html>heat</html>')
    assert artifact == dispatched.artifact
    return path, supervisor, authority, dispatched, Store(artifact.key, payload)


@pytest.mark.parametrize('schema_version', [13, 14])
@pytest.mark.skipif(sys.platform != 'linux' or not os.environ.get('ATOM_VERIFIER_TEST_REAL_STORE'),
                    reason='requires target Linux Docker daemon and real ArtifactStore')
def test_private_verifier_process_owns_browser_and_registers_real_result(adopted, tmp_path, schema_version):
    path, receipt, intent = adopted
    with sqlite3.connect(path) as db:
        db.execute('UPDATE requirements SET checks_json=? WHERE project_id=?',
                   (json.dumps([{'type':'exists','selector':'body'}]), 'project'))
    intent['expected_contract'] = capture_contract([{
        'key':'page', 'title':'Page', 'detail':'',
        'checks':[{'type':'exists','selector':'body'}]}]).digest
    migrate(path, tmp_path / 'before-v13.db', target_version=13)
    reserved = VerificationRepository(path).reserve(**intent)
    if schema_version == 14:
        migrate(path, tmp_path / 'before-v14.db', target_version=14)
    payload, artifact = snapshot(b'<html>heat</html>')
    assert artifact == receipt.artifact
    root = tmp_path / 'artifacts'
    root.mkdir(mode=0o700)
    assert ArtifactStore(root).put(payload) == artifact
    token = secrets.token_urlsafe(48)
    config = VerifierProcessConfig(path, root, IMAGE, PROFILE, 'service-worker', token)
    assert config.verifier_id == 'service-worker'
    with pytest.raises(VerifierStartupError, match='verifier_schema_required'):
        create_verifier_app(VerifierProcessConfig(tmp_path / 'before-v13.db', root,
            IMAGE, PROFILE, 'service-worker', token))
    with pytest.raises(VerifierStartupError, match='verifier_configuration_invalid'):
        VerifierProcessConfig(path, root, IMAGE, PROFILE, 'service-worker', 'short')
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    port = listener.getsockname()[1]
    listener.close()
    environment = dict(os.environ, ATOM_VERIFIER_DB_PATH=str(path),
        ATOM_VERIFIER_ARTIFACT_DIR=str(root), ATOM_VERIFIER_IMAGE=IMAGE,
        ATOM_VERIFIER_SECCOMP_PATH=str(PROFILE), ATOM_VERIFIER_ID=config.verifier_id,
        ATOM_VERIFIER_CONTROL_TOKEN=token)
    command = [sys.executable, '-m', 'uvicorn', 'app.verifier_service:create_app',
               '--factory', '--host', '127.0.0.1', '--port', str(port), '--log-level', 'error']
    process = subprocess.Popen(command, env=environment, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
    challenger = None
    try:
        with httpx.Client(base_url=f'http://127.0.0.1:{port}', trust_env=False,
                          timeout=40) as client:
            deadline = time.monotonic() + 15
            while True:
                assert process.poll() is None, 'verifier process exited before readiness'
                try:
                    denied = client.post('/v1/verify', json={'owner':'user',
                        'requestId':reserved.id})
                    break
                except httpx.ConnectError:
                    assert time.monotonic() < deadline, 'verifier startup deadline'
                    time.sleep(.05)
            assert denied.status_code == 401
            headers = {'authorization':f'Bearer {token}'}
            with socket.socket() as challenger_listener:
                challenger_listener.bind(('127.0.0.1', 0))
                challenger_port = challenger_listener.getsockname()[1]
            challenger = subprocess.Popen(command[:-4] + ['--port',str(challenger_port),
                '--log-level','error'], env=environment, stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE)
            _stdout, challenge_error = challenger.communicate(timeout=12)
            assert challenger.returncode != 0
            assert b'verifier_owner_unavailable' in challenge_error
            assert client.post('/v1/verify', json={'owner':'foreign',
                'requestId':reserved.id}, headers=headers).status_code == 404
            invalid = client.post('/v1/verify', content=b'{"owner":"user","owner":"user",'
                + b'"requestId":"' + reserved.id.encode() + b'"}',
                headers=headers | {'content-type':'application/json'})
            assert invalid.status_code == 400
            async def trusted_dispatch():
                async with VerifierClient(f'http://127.0.0.1:{port}', token) as transport:
                    result = await transport.verify(owner='user', request_id=reserved.id)
                    assert result == VerifierObservation(reserved.id,
                        reserved.revision_id, 'passed', 1, 1)
                    with pytest.raises(VerifierClientError, match='verifier_already_dispatched'):
                        await transport.verify(owner='user', request_id=reserved.id)
            asyncio.run(trusted_dispatch())
            replay = client.post('/v1/verify', json={'owner':'user',
                'requestId':reserved.id}, headers=headers)
            assert replay.status_code == 409
            assert replay.json() == {'error':'verifier_already_dispatched'}
            slow_checks = [{'type':'flow','selector':'#missing','expect':'body'}]
            with sqlite3.connect(path) as db:
                db.execute('UPDATE requirements SET checks_json=? WHERE project_id=?',
                           (json.dumps(slow_checks), 'project'))
            slow_contract = capture_contract([{'key':'page','title':'Page','detail':'',
                'checks':slow_checks}]).digest
            slow = VerificationRepository(path).reserve(**(intent | {
                'request_id':'abandoned-http', 'expected_contract':slow_contract}))
            with pytest.raises(httpx.ReadTimeout):
                client.post('/v1/verify', json={'owner':'user','requestId':slow.id},
                            headers=headers, timeout=.2)
            deadline = time.monotonic() + 10
            while True:
                with sqlite3.connect(path) as db:
                    dispatched = db.execute('SELECT 1 FROM verification_dispatches '
                        'WHERE request_id=?', (slow.id,)).fetchone() is not None
                if dispatched:
                    break
                assert time.monotonic() < deadline, 'abandoned request was not dispatched'
                time.sleep(.02)
            busy = client.post('/v1/verify', json={'owner':'user',
                'requestId':slow.id}, headers=headers)
            assert busy.status_code == 503 and busy.json() == {'error':'verifier_busy'}
            deadline = time.monotonic() + 45
            while True:
                settled = client.post('/v1/verify', json={'owner':'user',
                    'requestId':slow.id}, headers=headers)
                if settled.status_code == 409:
                    assert settled.json() == {'error':'verifier_already_dispatched'}
                    break
                assert settled.status_code == 503 and time.monotonic() < deadline
                time.sleep(.1)
        with sqlite3.connect(path) as db:
            assert db.execute('SELECT outcome FROM verification_results WHERE request_id=?',
                              (reserved.id,)).fetchone() == ('passed',)
            assert db.execute('SELECT outcome FROM verification_results WHERE request_id=?',
                              (slow.id,)).fetchone() == ('failed',)
            assert db.execute('SELECT count(*) FROM verification_attestations').fetchone() == (2,)
            assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        inventory = subprocess.run(['docker','ps','-aq','--filter',
            'label=atom.verifier.owner=service-worker'], capture_output=True,
            text=True, check=True)
        assert inventory.stdout.strip() == ''
    finally:
        if challenger is not None and challenger.poll() is None:
            challenger.terminate()
            challenger.wait(timeout=10)
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        assert process.returncode is not None
        leases = subprocess.run(['docker','ps','-aq','--filter',
            'label=atom.verifier-coordinator-lease.owner'], capture_output=True,
            text=True, check=True)
        assert leases.stdout.strip() == ''


def test_actual_isolated_browser_registers_one_v13_result(assignment):
    path, supervisor, authority, dispatched, store = assignment
    with VerifierCoordinator(supervisor) as coordinator:
        result = coordinator.verify_and_register(assignment=dispatched, store=store,
                                                 authority=authority, budget_seconds=20)
        assert store.reads == 1
        with pytest.raises(Exception):
            coordinator.verify_and_register(assignment=dispatched, store=store,
                                            authority=authority, budget_seconds=20)
    assert result.outcome == 'passed' and result.passed == result.total == 1
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM verification_attestations').fetchone() == (1,)
        assert db.execute('SELECT count(*) FROM verification_results').fetchone() == (1,)


@pytest.mark.parametrize('assignment', ['v13', 'v14'], indirect=True)
@pytest.mark.skipif(sys.platform != 'linux' or not os.environ.get('ATOM_VERIFIER_TEST_REAL_STORE'),
                    reason='requires target Linux Docker daemon and real ArtifactStore')
def test_actual_browser_attestation_publishes_exact_pinned_store_bytes(assignment, tmp_path):
    path, supervisor, authority, dispatched, fixture_store = assignment
    root = tmp_path / 'artifacts'
    root.mkdir(mode=0o700)
    store = ArtifactStore(root)
    assert store.put(fixture_store.payload) == dispatched.artifact
    with VerifierCoordinator(supervisor) as coordinator:
        observed = coordinator.verify_and_register(assignment=dispatched, store=store,
                                                   authority=authority, budget_seconds=20)
        assert observed.outcome == 'passed' and observed.passed == observed.total == 1
    request = dispatched.request
    intent = dict(owner='user', project_id=request.project_id,
        release_id='browser-observed-release', verification_id=request.id,
        expected_revision=request.revision_id, expected_generation=0,
        policy_digest=request.policy_digest, runner_version=request.runner_version,
        audience='public', slug='browser-observed-site')
    release = ReleaseRepository(path).publish_verified(store, **intent)
    content = ContentRepository(path)
    binding = content.sharing_binding(slug=release.slug)
    assert content.bind(owner='user', project_id='project', release_id=release.release_id) == binding
    with materialized_content(content, store, binding_id=binding.id) as view:
        assert view.publication.revision_id == request.revision_id
        assert view.publication.artifact == dispatched.artifact
        assert (view.path / 'index.html').read_bytes() == b'<html>heat</html>'
    service = create_content_app(ContentProcessConfig(path, root,
        'content.example.test', 'https://console.example.org'))

    async def serve(available):
        origin = service.hosts.url(binding.id)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=service),
                                     base_url=origin) as client:
            page = await client.get('/')
            shared = await client.get(service.hosts.sharing_url(release.slug),
                                      follow_redirects=False)
            if available:
                assert page.status_code == 200 and page.content == b'<html>heat</html>'
                assert page.headers['x-atom-release'] == release.release_id
                assert page.headers['x-atom-revision'] == request.revision_id
                assert shared.status_code == 307 and shared.headers['location'] == origin
            else:
                assert page.status_code == 404 and shared.status_code == 404
            assert page.headers['cache-control'] == 'no-store'

    asyncio.run(serve(True))
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    port = listener.getsockname()[1]
    listener.close()
    environment = dict(os.environ, ATOM_CONTENT_DB_PATH=str(path),
        ATOM_CONTENT_ARTIFACT_DIR=str(root), ATOM_CONTENT_HOST_SUFFIX='content.example.test',
        ATOM_CONTENT_CONSOLE_ORIGIN='https://console.example.org')
    process = subprocess.Popen([sys.executable, '-m', 'uvicorn',
        'app.content_entry:create_app', '--factory', '--host', '127.0.0.1', '--port', str(port),
        '--log-level', 'error'], env=environment, stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE)
    try:
        with httpx.Client(base_url=f'http://127.0.0.1:{port}', trust_env=False,
                          timeout=2) as client:
            deadline = time.monotonic() + 10
            while True:
                assert process.poll() is None, 'content process exited before readiness'
                try:
                    page = client.get('/', headers={'host':service.hosts.hostname(binding.id)})
                    break
                except httpx.ConnectError:
                    assert time.monotonic() < deadline, 'content process startup deadline'
                    time.sleep(.05)
            assert page.status_code == 200 and page.content == b'<html>heat</html>'
            shared = client.get('/s/' + release.slug,
                                headers={'host':'share.content.example.test'})
            assert shared.status_code == 307
            assert shared.headers['location'] == service.hosts.url(binding.id)
            ReleaseRepository(path).unpublish(owner='user', project_id='project',
                command_id='browser-release-off', expected_release=release.release_id,
                expected_generation=release.generation)
            assert client.get('/', headers={'host':service.hosts.hostname(binding.id)}).status_code == 404
            assert client.get('/s/' + release.slug,
                              headers={'host':'share.content.example.test'}).status_code == 404
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=5)
        assert process.returncode is not None
    asyncio.run(serve(False))
    with pytest.raises(VerificationError, match='content_not_found'):
        content.sharing_binding(slug=release.slug)
    with pytest.raises(VerificationError, match='release_not_found'):
        content.resolve(binding_id=binding.id)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT outcome FROM verification_results').fetchone() == ('passed',)
        assert db.execute('SELECT count(*) FROM verification_attestations').fetchone() == (1,)
        assert db.execute('SELECT event_kind FROM security_audit_events ORDER BY sequence').fetchall() == [
            ('release.published',), ('release.unpublished',)]
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    inventory = subprocess.run(['docker', 'ps', '-aq', '--filter',
        f'label=atom.verifier.request={request.id}'], capture_output=True, timeout=10, check=True)
    assert not inventory.stdout.strip()


def test_cold_start_reaper_finds_no_live_worker(assignment):
    _, supervisor, _, _, _ = assignment
    coordinator = VerifierCoordinator(supervisor)
    try:
        assert coordinator.start() == 0
    finally:
        coordinator.close()


def test_supervisor_requires_a_matching_live_lease(assignment):
    _, supervisor, authority, dispatched, store = assignment
    with pytest.raises(TypeError):
        supervisor.reap_orphans()
    with pytest.raises(TypeError):
        supervisor.verify_and_register(assignment=dispatched, store=store,
                                       authority=authority, budget_seconds=20)
    other = VerifierCoordinator(VerifierSupervisor(
        image=IMAGE, seccomp_path=PROFILE, verifier_id='different-worker'))
    try:
        other.start()
        with pytest.raises(SupervisorError, match='verifier_coordinator_lease_lost'):
            supervisor.reap_orphans(lease=other.lease)
    finally:
        other.close()


def test_coordinator_lease_excludes_second_owner_and_recovers(assignment):
    _, supervisor, _, _, _ = assignment
    first = VerifierCoordinator(supervisor)
    second = VerifierCoordinator(supervisor)
    try:
        assert first.start() == 0
        with pytest.raises(DaemonLeaseError, match='^verifier_coordinator_identity_in_use$'):
            second.start()
        assert first.lease.alive
    finally:
        second.close()
        first.close()
    assert second.start() == 0
    second.close()


@pytest.mark.skipif(sys.platform != 'linux' or not os.environ.get('ATOM_VERIFIER_TEST_REAL_STORE'),
                    reason='requires target Linux Docker daemon and process signals')
@pytest.mark.parametrize('assignment', ['slow'], indirect=True)
def test_second_coordinator_cannot_reap_live_browser_then_recovers_after_death(assignment):
    path, supervisor, authority, dispatched, store = assignment
    label = f'label=atom.verifier.request={dispatched.request.id}'

    def run_coordinator():
        with VerifierCoordinator(supervisor) as coordinator:
            coordinator.verify_and_register(assignment=dispatched, store=store,
                                            authority=authority, budget_seconds=20)

    process = multiprocessing.get_context('fork').Process(target=run_coordinator)
    process.start()
    second = VerifierCoordinator(supervisor)
    try:
        deadline = time.monotonic() + 15
        identity = ''
        while time.monotonic() < deadline and process.is_alive():
            inventory = subprocess.run(['docker', 'ps', '-q', '--filter', label],
                                       capture_output=True, timeout=10, check=True)
            identity = inventory.stdout.decode().strip()
            if identity:
                processes = subprocess.run(['docker', 'top', identity],
                                           capture_output=True, timeout=10, check=False)
                if processes.returncode == 0 and b'chrome-headless-shell' in processes.stdout:
                    break
            time.sleep(0.05)
        else:
            pytest.fail('coordinator browser was never observed running')
        with pytest.raises(DaemonLeaseError, match='^verifier_coordinator_identity_in_use$'):
            second.start()
        assert subprocess.run(['docker', 'inspect', identity], capture_output=True,
                              timeout=10).returncode == 0
        os.kill(process.pid, signal.SIGKILL)
        process.join(timeout=10)
        assert process.exitcode == -signal.SIGKILL
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                reaped = second.start()
                break
            except DaemonLeaseError as exc:
                if exc.code != 'verifier_coordinator_identity_in_use':
                    raise
                time.sleep(0.1)
        else:
            pytest.fail('successor could not acquire verifier identity')
        assert reaped >= 1
        assert subprocess.run(['docker', 'inspect', identity], capture_output=True,
                              timeout=10).returncode != 0
    finally:
        if process.is_alive():
            process.kill()
            process.join(timeout=10)
        second.close()
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM verification_attestations').fetchone() == (0,)
        assert db.execute('SELECT count(*) FROM verification_results').fetchone() == (0,)
    assert VerificationRepository(path).terminate(owner='user',
        request_id=dispatched.request.id, outcome='cancelled').outcome == 'cancelled'


@pytest.mark.parametrize('assignment', ['slow'], indirect=True)
def test_lost_coordinator_lease_cannot_register_and_successor_reaps(assignment):
    path, supervisor, authority, dispatched, store = assignment
    first = VerifierCoordinator(supervisor)
    second = VerifierCoordinator(supervisor)
    label = f'label=atom.verifier.request={dispatched.request.id}'
    try:
        assert first.start() == 0
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(first.verify_and_register, assignment=dispatched,
                                  store=store, authority=authority, budget_seconds=20)
            deadline = time.monotonic() + 12
            identity = ''
            while time.monotonic() < deadline and not pending.done():
                inventory = subprocess.run(['docker', 'ps', '-q', '--filter', label],
                                           capture_output=True, timeout=10, check=True)
                identity = inventory.stdout.decode().strip()
                if identity:
                    break
                time.sleep(0.05)
            assert identity, 'browser container was never observed running'
            subprocess.run(['docker', 'container', 'rm', '--force', first.lease.name],
                           capture_output=True, timeout=10, check=True)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and first.lease.alive:
                time.sleep(0.05)
            assert not first.lease.alive
            assert second.start() >= 1
            with pytest.raises(SupervisorError, match='verifier_coordinator_lease_lost'):
                pending.result(timeout=15)
    finally:
        second.close()
        first.close()
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM verification_attestations').fetchone() == (0,)
        assert db.execute('SELECT count(*) FROM verification_results').fetchone() == (0,)
    assert subprocess.run(['docker', 'ps', '-aq', '--filter', label],
                          capture_output=True, timeout=10, check=True).stdout.strip() == b''


def test_tampered_stored_artifact_never_starts_or_registers(assignment):
    path, supervisor, authority, dispatched, store = assignment
    store.payload = store.payload[:-1] + b'X'
    with VerifierCoordinator(supervisor) as coordinator:
        with pytest.raises(SupervisorError, match='verifier_artifact_mismatch'):
            coordinator.verify_and_register(assignment=dispatched, store=store,
                                            authority=authority)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM verification_results').fetchone() == (0,)


@pytest.mark.parametrize('assignment', ['slow'], indirect=True)
def test_browser_deadline_leaves_no_result_or_container(assignment):
    path, supervisor, authority, dispatched, store = assignment
    with VerifierCoordinator(supervisor) as coordinator:
        with pytest.raises(SupervisorError, match='verifier_execution_failed'):
            coordinator.verify_and_register(assignment=dispatched, store=store,
                                            authority=authority, budget_seconds=1)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM verification_results').fetchone() == (0,)
    inventory = subprocess.run(['docker', 'ps', '-aq', '--filter',
        f'label=atom.verifier.request={dispatched.request.id}'],
        capture_output=True, timeout=10, check=True)
    assert not inventory.stdout.strip()


@pytest.mark.parametrize('assignment', ['slow'], indirect=True)
def test_killed_browser_container_leaves_no_result_or_container(assignment):
    path, supervisor, authority, dispatched, store = assignment
    label = f'label=atom.verifier.request={dispatched.request.id}'

    def running_container():
        probe = subprocess.run(['docker', 'ps', '-q', '--filter', label],
                               capture_output=True, timeout=10, check=True)
        return probe.stdout.decode().strip()

    with VerifierCoordinator(supervisor) as coordinator:
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(coordinator.verify_and_register, assignment=dispatched,
                                  store=store, authority=authority, budget_seconds=20)
            deadline = time.monotonic() + 12
            identity = ''
            while time.monotonic() < deadline and not pending.done():
                identity = running_container()
                if identity:
                    break
                time.sleep(0.05)
            assert identity, 'browser container was never observed running'
            subprocess.run(['docker', 'kill', identity], capture_output=True,
                           timeout=10, check=True)
            with pytest.raises(SupervisorError, match='verifier_execution_failed'):
                pending.result(timeout=15)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM verification_results').fetchone() == (0,)
        assert db.execute('SELECT count(*) FROM verification_attestations').fetchone() == (0,)
    assert not running_container()
    inventory = subprocess.run(['docker', 'ps', '-aq', '--filter', label],
                               capture_output=True, timeout=10, check=True)
    assert not inventory.stdout.strip()
    ledger = VerificationRepository(path)
    closed = ledger.terminate(owner='user', request_id=dispatched.request.id,
                              outcome='cancelled')
    assert closed.outcome == 'cancelled'
    assert ledger.terminate(owner='user', request_id=dispatched.request.id,
                            outcome='cancelled') == closed
    with pytest.raises(VerificationError, match='verification_expired'):
        authority.register(request_id=dispatched.request.id,
            route_id=dispatched.route_id, verifier_id=dispatched.verifier_id,
            environment_digest=dispatched.environment_digest,
            artifact=dispatched.artifact, credential=dispatched.credential,
            results=[{'key': 'page', 'checkIndex': 0, 'passed': True, 'note': 'observed'}])
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT outcome FROM verification_results').fetchone() == ('cancelled',)
        assert db.execute('SELECT count(*) FROM verification_attestations').fetchone() == (0,)


def test_changed_contract_during_real_browser_execution_cannot_register(assignment):
    path, supervisor, authority, dispatched, store = assignment

    def change_contract():
        with sqlite3.connect(path) as db:
            db.execute("UPDATE requirements SET title='Changed' WHERE project_id='project'")

    store.hook = change_contract
    with VerifierCoordinator(supervisor) as coordinator:
        with pytest.raises(VerificationError, match='verification_stale_evidence'):
            coordinator.verify_and_register(assignment=dispatched, store=store,
                                            authority=authority, budget_seconds=20)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM verification_results').fetchone() == (0,)
        assert db.execute('SELECT count(*) FROM verification_attestations').fetchone() == (0,)


@pytest.mark.parametrize('assignment', ['slow'], indirect=True)
def test_changed_head_during_real_browser_execution_cannot_register(assignment):
    path, supervisor, authority, dispatched, store = assignment
    label = f'label=atom.verifier.request={dispatched.request.id}'

    with VerifierCoordinator(supervisor) as coordinator:
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(coordinator.verify_and_register, assignment=dispatched,
                                  store=store, authority=authority, budget_seconds=20)
            deadline = time.monotonic() + 12
            browser_running = False
            while time.monotonic() < deadline and not pending.done():
                inventory = subprocess.run(['docker', 'ps', '-q', '--filter', label],
                                           capture_output=True, timeout=10, check=True)
                identity = inventory.stdout.decode().strip()
                if identity:
                    processes = subprocess.run(['docker', 'top', identity],
                                               capture_output=True, timeout=10, check=False)
                    browser_running = processes.returncode == 0 and b'chrome-headless-shell' in processes.stdout
                    if browser_running:
                        break
                time.sleep(0.05)
            assert browser_running, 'Chromium was never observed running'
            with sqlite3.connect(path) as db:
                db.execute('UPDATE revision_workspaces SET current_revision_id=? WHERE id=?',
                           ('main-root', dispatched.request.workspace_id))
            with pytest.raises(VerificationError, match='verification_stale_evidence'):
                pending.result(timeout=15)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM verification_results').fetchone() == (0,)
        assert db.execute('SELECT count(*) FROM verification_attestations').fetchone() == (0,)


def test_wrong_credential_and_replay_cannot_register_real_browser_result(assignment, monkeypatch):
    path, supervisor, authority, dispatched, store = assignment
    results = [{'key': 'page', 'checkIndex': 0, 'passed': True, 'note': 'observed'}]
    scope = dict(request_id=dispatched.request.id, route_id=dispatched.route_id,
                 verifier_id=dispatched.verifier_id,
                 environment_digest=dispatched.environment_digest,
                 artifact=dispatched.artifact, results=results)
    with pytest.raises(VerificationError, match='verifier_unauthorized'):
        authority.register(**scope, credential=os.urandom(32))

    import app.verifier_supervisor as module
    original = module.run_verifier_bounded

    def inspect_input(args, *, timeout, output_limit, input_data):
        assert dispatched.credential not in input_data
        assert dispatched.credential.hex() not in ' '.join(args)
        return original(args, timeout=timeout, output_limit=output_limit,
                        input_data=input_data)

    monkeypatch.setattr(module, 'run_verifier_bounded', inspect_input)
    with VerifierCoordinator(supervisor) as coordinator:
        result = coordinator.verify_and_register(assignment=dispatched, store=store,
                                                 authority=authority, budget_seconds=20)
    assert result.outcome == 'passed'
    with pytest.raises(VerificationError, match='verification_expired'):
        authority.register(**scope, credential=dispatched.credential)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM verification_results').fetchone() == (1,)
        assert db.execute('SELECT count(*) FROM verification_attestations').fetchone() == (1,)


@pytest.mark.skipif(sys.platform != 'linux' or not os.environ.get('ATOM_VERIFIER_TEST_REAL_STORE'),
                    reason='requires actual Linux ArtifactStore and local Docker daemon')
def test_target_linux_real_store_and_browser_register_once(assignment, tmp_path):
    path, supervisor, authority, dispatched, _ = assignment
    payload, artifact = snapshot(b'<html>heat</html>')
    root = tmp_path / 'artifacts'
    root.mkdir(mode=0o700)
    store = ArtifactStore(root)
    assert store.put(payload) == artifact == dispatched.artifact
    with VerifierCoordinator(supervisor) as coordinator:
        result = coordinator.verify_and_register(assignment=dispatched, store=store,
                                                 authority=authority, budget_seconds=20)
    assert result.outcome == 'passed' and result.passed == 1
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM verification_attestations').fetchone() == (1,)
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
