import json
import os
from pathlib import Path

import pytest

from app.migrations import migrate
from app.sandbox.docker_driver import run_bounded
from test_retention_plan import planned, reader, audited_release, release, ledger, legacy

IMAGE = os.environ.get('ATOM_TEST_API_IMAGE')
pytestmark = pytest.mark.skipif(not IMAGE, reason='requires explicit pinned local API image')


@pytest.mark.parametrize('scenario', ['happy','cli','authority-probe','hold','receiver','corrupt','crash-archive-before','crash-archive-after',
    'crash-recover-before','crash-recover-after'])
def test_actual_store_source_registration_and_recovery(planned, tmp_path, scenario):
    path, _ = planned
    migrate(path, tmp_path/'before-nine.db', target_version=9)
    run_probe(path, scenario)


def run_probe(path, scenario):
    backend = Path(__file__).resolve().parents[2]
    # Fixture policy's actual configured opaque store ID.
    import sqlite3
    with sqlite3.connect(path) as db:
        store_id = db.execute('SELECT archive_store_id FROM security_audit_retention_policies').fetchone()[0]
    command = ['docker','run','--rm','--network=none','--read-only','--cap-drop=ALL','--security-opt=no-new-privileges',
        '--user','1000:1000','--tmpfs','/tmp:rw,nosuid,nodev,size=32m',
        '--mount',f'type=bind,source={backend},target=/src,readonly',
        '--mount',f'type=bind,source={path},target=/seed.db,readonly',
        '--workdir','/src','--env','PYTHONPATH=/src','--entrypoint','python',IMAGE,
        '-B','/src/tests/integration/_audit_archiving_probe.py',scenario,store_id]
    status, out, err = run_bounded(command,timeout=30)
    assert status == 0, err.decode()
    assert json.loads(out)['scenario'] == scenario


@pytest.mark.parametrize('scenario',['pages','pages-hold'])
def test_real_business_events_two_cli_pages(reader, tmp_path, monkeypatch, scenario):
    from app.audit_delivery import AuditDeliveryRepository
    from app.audit_governance import AuditGovernanceRepository
    from app.audit_retention import RetentionRepository
    from test_audit_retention import args
    path, _, access, _, _ = reader
    for index in range(101):
        monkeypatch.setattr('app.access_repository.time.time',lambda index=index: 200+index*61)
        access.create_console_session(user_id='user',lifetime_seconds=60)
    migrate(path,tmp_path/'before-seven.db',target_version=7)
    AuditGovernanceRepository(path).execute(command_id='register',operator_id='operator',destination_id='sink',
        scope_kind='account',scope_id='user',action='register',expected_generation=0)
    delivery = AuditDeliveryRepository(path,destination_id='sink',scope_kind='account',scope_id='user')
    for _ in range(2):
        delivery.enroll()
        lease = delivery.claim()
        delivery.acknowledge(event_ids=[row['event_id'] for row in lease.events],lease_owner=lease.owner)
    migrate(path,tmp_path/'before-nine.db',target_version=9)
    RetentionRepository(path).execute(**args(state='active',min_age_seconds=1))
    run_probe(path,scenario)
