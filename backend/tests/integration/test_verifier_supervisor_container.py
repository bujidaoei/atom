"""Real Docker report enters v13 only through the trusted supervised path."""
import json
import multiprocessing
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
import time

import pytest

from app.migrations import migrate
from app.artifacts import ArtifactStore
from app.verification_contract import capture_contract
from app.verification_repository import VerificationRepository
from app.verification_repository import VerificationError
from app.verifier_authority import VerifierAuthority
from app.verifier_supervisor import SupervisorError, VerifierSupervisor
from app.verifier_coordinator import VerifierCoordinator
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
    request = VerificationRepository(path).reserve(**intent)
    authority = VerifierAuthority(path)
    supervisor = VerifierSupervisor(image=IMAGE, seccomp_path=PROFILE, verifier_id='worker-1')
    dispatched = authority.dispatch(owner='user', request_id=request.id,
        artifact=receipt.artifact, route_id='a' * 32, verifier_id='worker-1',
        environment_digest=supervisor.environment_digest)
    payload, artifact = snapshot(b'<html>heat</html>')
    assert artifact == dispatched.artifact
    return path, supervisor, authority, dispatched, Store(artifact.key, payload)


def test_actual_isolated_browser_registers_one_v13_result(assignment):
    path, supervisor, authority, dispatched, store = assignment
    result = supervisor.verify_and_register(assignment=dispatched, store=store,
                                            authority=authority, budget_seconds=20)
    assert result.outcome == 'passed' and result.passed == result.total == 1
    assert store.reads == 1
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM verification_attestations').fetchone() == (1,)
        assert db.execute('SELECT count(*) FROM verification_results').fetchone() == (1,)
    with pytest.raises(Exception):
        supervisor.verify_and_register(assignment=dispatched, store=store,
                                       authority=authority, budget_seconds=20)


def test_cold_start_reaper_finds_no_live_worker(assignment):
    _, supervisor, _, _, _ = assignment
    assert supervisor.reap_orphans() == 0


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


def test_tampered_stored_artifact_never_starts_or_registers(assignment):
    path, supervisor, authority, dispatched, store = assignment
    store.payload = store.payload[:-1] + b'X'
    with pytest.raises(SupervisorError, match='verifier_artifact_mismatch'):
        supervisor.verify_and_register(assignment=dispatched, store=store,
                                       authority=authority)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM verification_results').fetchone() == (0,)


@pytest.mark.parametrize('assignment', ['slow'], indirect=True)
def test_browser_deadline_leaves_no_result_or_container(assignment):
    path, supervisor, authority, dispatched, store = assignment
    with pytest.raises(SupervisorError, match='verifier_execution_failed'):
        supervisor.verify_and_register(assignment=dispatched, store=store,
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

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(supervisor.verify_and_register, assignment=dispatched,
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


@pytest.mark.skipif(sys.platform != 'linux' or not os.environ.get('ATOM_VERIFIER_TEST_REAL_STORE'),
                    reason='requires target Linux Docker daemon and process signals')
@pytest.mark.parametrize('assignment', ['slow'], indirect=True)
def test_coordinator_process_death_reaps_browser_and_recovers_ledger(assignment):
    path, supervisor, authority, dispatched, store = assignment
    assert supervisor.reap_orphans() == 0

    def run_coordinator():
        supervisor.verify_and_register(assignment=dispatched, store=store,
                                       authority=authority, budget_seconds=20)

    process = multiprocessing.get_context('fork').Process(target=run_coordinator)
    process.start()
    label = f'label=atom.verifier.owner={supervisor.verifier_id}'
    try:
        deadline = time.monotonic() + 12
        browser_running = False
        while time.monotonic() < deadline and process.is_alive():
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
        os.kill(process.pid, signal.SIGKILL)
        process.join(timeout=10)
        assert process.exitcode == -signal.SIGKILL
        assert supervisor.reap_orphans() >= 1
    finally:
        if process.is_alive():
            process.kill()
            process.join(timeout=10)
        supervisor.reap_orphans()
    assert supervisor.reap_orphans() == 0
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM verification_results').fetchone() == (0,)
        assert db.execute('SELECT count(*) FROM verification_attestations').fetchone() == (0,)
    closed = VerificationRepository(path).terminate(owner='user',
        request_id=dispatched.request.id, outcome='cancelled')
    assert closed.outcome == 'cancelled'


def test_changed_contract_during_real_browser_execution_cannot_register(assignment):
    path, supervisor, authority, dispatched, store = assignment

    def change_contract():
        with sqlite3.connect(path) as db:
            db.execute("UPDATE requirements SET title='Changed' WHERE project_id='project'")

    store.hook = change_contract
    with pytest.raises(VerificationError, match='verification_stale_evidence'):
        supervisor.verify_and_register(assignment=dispatched, store=store,
                                       authority=authority, budget_seconds=20)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM verification_results').fetchone() == (0,)
        assert db.execute('SELECT count(*) FROM verification_attestations').fetchone() == (0,)


@pytest.mark.parametrize('assignment', ['slow'], indirect=True)
def test_changed_head_during_real_browser_execution_cannot_register(assignment):
    path, supervisor, authority, dispatched, store = assignment
    label = f'label=atom.verifier.request={dispatched.request.id}'

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(supervisor.verify_and_register, assignment=dispatched,
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
    result = supervisor.verify_and_register(assignment=dispatched, store=store,
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
    result = supervisor.verify_and_register(assignment=dispatched, store=store,
                                            authority=authority, budget_seconds=20)
    assert result.outcome == 'passed' and result.passed == 1
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM verification_attestations').fetchone() == (1,)
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
