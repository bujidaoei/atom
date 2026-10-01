import json
import os
from pathlib import Path
import socket
import sqlite3
import threading
import time
import uuid

import pytest
import uvicorn

from app.migrations import migrate
from app.sandbox.docker_driver import run_bounded
from test_audit_recovery_http import recovery, planned, reader, audited_release, release, ledger, legacy, IMAGE

API_IMAGE = os.environ.get('ATOM_TEST_API_IMAGE')
pytestmark = pytest.mark.skipif(not IMAGE or not API_IMAGE,reason='requires pinned API and sandbox images')


_V10_SCENARIOS = ['happy','auth','policy','lost-result','worker','cancelled','cli','commit-before','commit-after',
    'pages','pages-hold','missing','corrupt','cold-read','prune-happy','prune-reader','prune-cli','prune-commit-before','prune-commit-after','prune-hold','prune-corrupt','prune-verifier','prune-missing-receipt','prune-rollback']
_V13_SCENARIOS = ['happy','auth','lost-result','commit-before','commit-after','pages-hold']


@pytest.mark.parametrize('scenario,schema_version',
    [(scenario,10) for scenario in _V10_SCENARIOS] + [(scenario,13) for scenario in _V13_SCENARIOS])
def test_real_linux_owner_wire_worker_and_receipt(planned,recovery,tmp_path,monkeypatch,scenario,schema_version):
    path,_ = planned
    migrate(path,tmp_path/'before-ten.db',target_version=10)
    if schema_version == 13:
        from app.release_repository import ReleaseRepository
        ReleaseRepository(path).unpublish(owner='user',project_id='project',command_id='prepare-v13',
            expected_release='release',expected_generation=1)
        for version in (11, 12, 13):
            migrate(path,tmp_path/f'before-{version}.db',target_version=version)
    if scenario in ('pages','pages-hold'):
        from app.access_repository import AccessRepository
        from app.audit_delivery import AuditDeliveryRepository
        access = AccessRepository(path)
        with monkeypatch.context() as clock:
            for index in range(99):
                clock.setattr(time,'time',lambda index=index:200+index*61)
                access.create_console_session(user_id='user',lifetime_seconds=60)
        delivery = AuditDeliveryRepository(path,destination_id='sink',scope_kind='account',scope_id='user')
        delivery.enroll()
        lease = delivery.claim()
        assert len(lease.events)==99
        delivery.acknowledge(event_ids=[row['event_id'] for row in lease.events],lease_owner=lease.owner)
    app,config,_,_,_ = recovery
    if scenario == 'worker':
        monkeypatch.setattr('app.sandbox.audit_recovery._PROGRAM','raise SystemExit(2)')
    sock = socket.socket()
    sock.bind(('0.0.0.0',0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False))
    thread = threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True)
    thread.start()
    volume = None
    try:
        deadline = time.monotonic()+10
        while not server.started and thread.is_alive() and time.monotonic()<deadline:
            time.sleep(.02)
        assert server.started
        backend = Path(__file__).resolve().parents[2]
        command = ['docker','run','--rm','-i','--read-only','--cap-drop=ALL','--security-opt=no-new-privileges',
            '--user','1000:1000','--tmpfs','/tmp:rw,nosuid,nodev,size=32m',
            '--mount',f'type=bind,source={backend},target=/src,readonly',
            '--mount',f'type=bind,source={path},target=/seed.db,readonly',
            '--workdir','/src','--env','PYTHONPATH=/src','--entrypoint','/app/backend/.venv/bin/python',API_IMAGE,
            '-B','/src/tests/integration/_isolated_receipt_probe.py']
        data = dict(port=port,token=config.admin_token,image=IMAGE,policy=app.state.lifecycle.driver.policy_digest,
                    scenario=scenario,schema_version=schema_version,
                    broker_host=os.environ.get('ATOM_TEST_DOCKER_HOST','host.docker.internal'))
        if scenario=='cold-read':
            volume='atom-audit-cold-'+uuid.uuid4().hex
            status,_,err=run_bounded(['docker','volume','create','--label','atom.test=audit-cold',volume])
            assert status==0,err.decode()
            status,_,err=run_bounded(['docker','run','--rm','--network=none','--mount',f'type=volume,source={volume},target=/saved',
                '--entrypoint','chown',API_IMAGE,'1000:1000','/saved'])
            assert status==0,err.decode()
            command[2:2]=['--mount',f'type=volume,source={volume},target=/saved']
            writer=volume+'-writer'
            status,out,err=run_bounded(command[:2]+['--name',writer]+command[2:],timeout=30,
                input_data=json.dumps(dict(data,scenario='cold-write')).encode())
            assert status==0,err.decode()
            saved=json.loads(out)
            assert saved['version']==schema_version
            data['backup_sha256']=saved['backup_sha256']
            # The --rm writer is gone; the reader receives only saved volume and application code.
            status,inventory,err=run_bounded(['docker','container','ls','--all','--filter',f'name=^/{writer}$','--format','{{.ID}}'])
            assert status==0 and not inventory.strip(),err.decode()
            saved_mount=command.index(f'type=volume,source={volume},target=/saved')
            command[saved_mount]+=',readonly'
            seed=command.index(f'type=bind,source={path},target=/seed.db,readonly')
            del command[seed-1:seed+1]
        status,out,err = run_bounded(command,timeout=30,input_data=json.dumps(data).encode())
        assert status == 0,err.decode()
        expected = 2 if scenario=='pages' else int(scenario.startswith('prune-') or scenario in ('happy','cli','commit-before','commit-after','pages-hold','cold-read'))
        assert json.loads(out) == {'scenario':scenario,'receipts':expected}
        assert not app.state.lifecycle.driver.owned_inventory()
        if scenario in ('cli','commit-before','commit-after'):
            with sqlite3.connect(config.registry_path) as db:
                assert db.execute('SELECT count(*) FROM attempts').fetchone() == (2 if scenario=='commit-before' else 1,)
    finally:
        server.should_exit = True
        thread.join(20)
        sock.close()
        assert not thread.is_alive()
        if volume is not None:
            status,metadata,err=run_bounded(['docker','volume','inspect',volume])
            assert status==0,err.decode()
            assert json.loads(metadata)[0]['Labels']['atom.test']=='audit-cold'
            status,_,err=run_bounded(['docker','volume','rm',volume])
            assert status==0,err.decode()
