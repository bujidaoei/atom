"""Real Linux owner/store; test-only TCP relay bridges Docker Desktop to host broker."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import select
import shutil
import socket
import socketserver
import sqlite3
import subprocess
import sys
import threading
from unittest.mock import patch

from app.audit_archiving import AuditArchiving
from app.audit_archive import ArchiveError
from app.audit_retention import RetentionError
from app.audit_event_format import EVENT_FIELDS
from app.sandbox.audit_recovery_client import AuditRecoveryClient
from app.sandbox.client import BrokerClientError
from app.migrations import backup_database, verify_backup
from app.audit_archive_store import AuditArchiveStore

config = json.load(sys.stdin)
if config['scenario']=='cold-read':
    assert not Path('/seed.db').exists()
    assert verify_backup(Path('/saved/source.db'),expected_version=10)==config['backup_sha256']
    with sqlite3.connect('/saved/source.db') as saved, sqlite3.connect('/tmp/source.db') as restored:
        saved.backup(restored)
else:
    shutil.copyfile('/seed.db', '/tmp/source.db')
os.chmod('/tmp/source.db', 0o600)
Path('/tmp/archive').mkdir(mode=0o700)
with sqlite3.connect('/tmp/source.db') as db:
    store = db.execute('SELECT archive_store_id FROM security_audit_retention_policies').fetchone()[0]
owner = AuditArchiving(Path('/tmp/source.db'),store_id=store,root=Path('/tmp/archive'))
if config['scenario']=='cold-read':
    with sqlite3.connect('/tmp/source.db') as db:
        db.row_factory=sqlite3.Row
        registered=dict(db.execute("SELECT * FROM security_audit_archives WHERE archive_id='archive'").fetchone())
    payload=AuditArchiveStore(Path('/saved/archive')).read(expected_sha256=registered['archive_sha256'])
    owner.store.put(payload,expected_sha256=registered['archive_sha256'])
else:
    registered = owner.archive(archive_id='archive',operator_id='operator',policy_id='policy',expected_generation=1)
if config['scenario']=='cold-write':
    Path('/saved/archive').mkdir(mode=0o700)
    payload=owner.store.read(expected_sha256=registered['archive_sha256'])
    AuditArchiveStore(Path('/saved/archive')).put(payload,expected_sha256=registered['archive_sha256'])
    backup=backup_database(Path('/tmp/source.db'),Path('/saved/source.db'))
    print(json.dumps({'backup_sha256':backup.sha256,'version':backup.version}))
    raise SystemExit(0)
if config['scenario'] in ('missing','corrupt'):
    file = Path('/tmp/archive')/(registered['archive_sha256']+'.atomaudit')
    if config['scenario']=='missing':
        file.unlink()
    else:
        file.chmod(0o600)
        file.write_bytes(b'corrupt')
request = dict(archive_id='archive',recovery_id='receipt',verifier_id='verifier')


class Relay(socketserver.BaseRequestHandler):
    def handle(self):
        with socket.create_connection(('host.docker.internal',config['port']),timeout=10) as remote:
            sockets = [self.request,remote]
            while True:
                readable,_,_ = select.select(sockets,[],[],50)
                if not readable: return
                for source in readable:
                    data = source.recv(65536)
                    if not data: return
                    (remote if source is self.request else self.request).sendall(data)


relay = socketserver.ThreadingTCPServer(('127.0.0.1',0),Relay)
relay.daemon_threads = True
thread = threading.Thread(target=relay.serve_forever,daemon=True)
thread.start()


async def run():
    scenario = config['scenario']
    async with AuditRecoveryClient(f'http://127.0.0.1:{relay.server_address[1]}',
            'x'*32 if scenario == 'auth' else config['token'],expected_image=config['image'],
            expected_policy_digest='0'*64 if scenario == 'policy' else config['policy']) as client:
        real = client.recover
        seen = []
        async def observe(*args,**kwargs):
            result = await real(*args,**kwargs)
            seen.append(result)
            if scenario == 'lost-result':
                raise BrokerClientError('test_result_lost')
            if scenario == 'cancelled':
                raise asyncio.CancelledError()
            return result
        client.recover = observe
        if scenario in ('auth','policy','lost-result','worker','cancelled','missing','corrupt'):
            try: await owner.recover_isolated(**request,client=client)
            except (BrokerClientError, asyncio.CancelledError, ArchiveError): pass
            else: raise AssertionError('failed verification issued receipt')
            expected = 0
        else:
            receipt = await owner.recover_isolated(**request,client=client)
            assert receipt['protocol'] == 'audit-recovery-v2'
            assert receipt['result_sha256'] == hashlib.sha256(json.dumps(seen[0],sort_keys=True,
                separators=(',',':'),ensure_ascii=True).encode()).hexdigest()
            assert await owner.recover_isolated(**request,client=client) == receipt
            assert len(seen) == 1
            if scenario=='cold-read':
                with sqlite3.connect('/tmp/source.db') as db:
                    db.row_factory=sqlite3.Row
                    original=[dict(row) for row in db.execute('SELECT '+','.join(EVENT_FIELDS)+
                        " FROM security_audit_events WHERE scope_kind='account' AND scope_id='user' "
                        "AND event_kind='console.session.created' ORDER BY sequence")]
                assert seen[0]['result']['events']==original
            try: await owner.recover_isolated(**dict(request,verifier_id='different'),client=client)
            except ArchiveError as error: assert str(error) == 'recovery_identity_conflict'
            else: raise AssertionError('identity conflict accepted')
            expected = 1
            if scenario.startswith('prune-'):
                return run_prune(receipt)
            if scenario in ('pages','pages-hold'):
                first = owner.inspect(archive_id='archive')
                assert first['archive']['event_count']==100 and first['continuation']
                continuation = dict(first['continuation'],archive_id='second',operator_id='operator')
                if scenario=='pages-hold':
                    owner.repository.execute(command_id='hold',policy_id='policy',operator_id='operator',action='place_hold',
                        expected_generation=1,hold_id='legal-hold',hold_kind='legal')
                    try: owner.archive(**continuation)
                    except RetentionError: pass
                    else: raise AssertionError('held continuation accepted')
                    with sqlite3.connect('/tmp/source.db') as db:
                        assert db.execute('SELECT count(*) FROM security_audit_archives').fetchone()==(1,)
                else:
                    second = owner.archive(**continuation)
                    assert second['event_count']==2
                    await owner.recover_isolated(archive_id='second',recovery_id='second',verifier_id='verifier',client=client)
                    assert len(seen)==2 and owner.inspect(archive_id='second')['continuation'] is None
                    with sqlite3.connect('/tmp/source.db') as db:
                        db.row_factory=sqlite3.Row
                        source = [dict(row) for row in db.execute('SELECT '+','.join(EVENT_FIELDS)+
                            " FROM security_audit_events WHERE scope_kind='account' AND scope_id='user' "
                            "AND event_kind='console.session.created' ORDER BY sequence")]
                    restored = seen[0]['result']['events']+seen[1]['result']['events']
                    assert len(source)==102 and restored==source
                    expected=2
        try: owner.recover(**request)
        except ArchiveError as error: assert str(error) == 'isolated_recovery_required'
        else: raise AssertionError('legacy receipt accepted on schema10')
        with sqlite3.connect('/tmp/source.db') as db:
            assert db.execute('SELECT count(*) FROM security_audit_isolated_recoveries').fetchone() == (expected,)
            assert db.execute('SELECT count(*) FROM security_audit_archive_recoveries').fetchone() == (0,)
        if scenario not in ('missing','corrupt'):
            inspection = owner.inspect(archive_id='archive')
            assert inspection['isolated_recovery_receipts'] == min(expected,1)
            assert inspection['recovery_receipts'] == 0 and not inspection['deletion_authorized']
    return expected


def run_prune(recovered):
    from app.audit_pruning import AuditPruning, PruneError
    from app.migrations import migrate
    scenario=config['scenario']
    if scenario=='prune-hold':
        owner.repository.execute(command_id='hold',policy_id='policy',operator_id='operator',action='place_hold',
            expected_generation=1,hold_id='legal-hold',hold_kind='legal')
    if scenario=='prune-corrupt':
        file=Path('/tmp/archive')/(registered['archive_sha256']+'.atomaudit')
        file.chmod(0o600);file.write_bytes(b'corrupt')
    migrate(Path('/tmp/source.db'),Path('/tmp/before-prune.db'),target_version=11)
    service=AuditPruning(Path('/tmp/source.db'),store_id=store,root=Path('/tmp/archive'),verifier_id='verifier',
        expected_image=config['image'],expected_policy_digest='0'*64 if scenario=='prune-verifier' else config['policy'])
    request=dict(command_id='prune',operator_id='operator',archive_id='archive',
        recovery_id='absent' if scenario=='prune-missing-receipt' else recovered['recovery_id'],
        expected_generation=1,expected_context=registered['context_sha256'])
    with sqlite3.connect('/tmp/source.db') as db:
        before=list(db.iterdump())
        original=db.execute('SELECT sequence,event_id,scope_kind,scope_id,event_kind FROM security_audit_events '
            "WHERE scope_kind='account' AND scope_id='user' AND event_kind='console.session.created' ORDER BY sequence").fetchall()
        unrelated=db.execute("SELECT * FROM security_audit_events WHERE NOT (scope_kind='account' AND scope_id='user' AND event_kind='console.session.created')").fetchall()
    if scenario=='prune-happy':
        result=service.prune(**request)
        assert result['event_count']==len(original)==3
        assert service.prune(**request)==result
        try:service.prune(**dict(request,operator_id='different'))
        except PruneError as error:assert str(error)=='prune_identity_conflict'
        else:raise AssertionError('changed replay accepted')
        with sqlite3.connect('/tmp/source.db') as db:
            assert db.execute('SELECT sequence,event_id,scope_kind,scope_id,event_kind FROM security_audit_archived_events ORDER BY sequence').fetchall()==original
            assert db.execute("SELECT * FROM security_audit_events WHERE NOT (scope_kind='account' AND scope_id='user' AND event_kind='console.session.created')").fetchall()==unrelated
            assert db.execute("SELECT count(*) FROM security_audit_events WHERE scope_kind='account' AND scope_id='user' AND event_kind='console.session.created'").fetchone()==(0,)
            assert db.execute('SELECT count(*) FROM security_audit_delivery').fetchone()==(0,)
            assert db.execute('SELECT count(*) FROM security_audit_prune_receipts').fetchone()==(1,)
            assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
    else:
        def attempt():
            try:service.prune(**request)
            except (PruneError,RetentionError,ArchiveError):return
            raise AssertionError('invalid prune succeeded')
        if scenario=='prune-rollback':
            connect=sqlite3.connect
            class Connection(sqlite3.Connection):
                def execute(self,sql,*args,**kwargs):
                    result=super().execute(sql,*args,**kwargs)
                    if sql.startswith('DELETE FROM security_audit_events'):
                        raise sqlite3.OperationalError('injected failure after actual delete')
                    return result
            with patch('sqlite3.connect',lambda *args,**kwargs:connect(*args,**dict(kwargs,factory=Connection))):attempt()
        else:attempt()
        with sqlite3.connect('/tmp/source.db') as db:assert list(db.iterdump())==before
    # Ordinary connections never inherit maintenance authority, including after rollback.
    with sqlite3.connect('/tmp/source.db') as db:
        assert db.execute('SELECT count(*) FROM security_audit_isolated_recoveries').fetchone()==(1,)
        try:db.execute('DELETE FROM security_audit_events')
        except sqlite3.DatabaseError:pass
        else:raise AssertionError('maintenance authority leaked')
    return 1


def run_cli():
    command = [sys.executable,'-B','-m','app.archive_admin','--database','/tmp/source.db',
        '--store-id',store,'--store-root','/tmp/archive','recover-isolated',
        '--archive-id','archive','--recovery-id','receipt','--verifier-id','verifier',
        '--broker-origin',f'http://127.0.0.1:{relay.server_address[1]}','--expected-image',config['image'],
        '--expected-policy-digest',config['policy']]
    environment = dict(os.environ,ATOM_BROKER_ADMIN_TOKEN=config['token'])
    if config['scenario'].startswith('commit-'):
        # Kill the actual CLI only around its receipt transaction, not during read transactions.
        script = '''
import os,sqlite3,sys,runpy
original=sqlite3.connect
class Connection(sqlite3.Connection):
    receipt=False
    def execute(self,sql,*args,**kwargs):
        if sql.startswith('INSERT INTO security_audit_isolated_recoveries '):self.receipt=True
        if sql=='COMMIT' and self.receipt and os.environ['CRASH_PHASE']=='commit-before':os._exit(71)
        result=super().execute(sql,*args,**kwargs)
        if sql=='COMMIT' and self.receipt and os.environ['CRASH_PHASE']=='commit-after':os._exit(72)
        return result
sqlite3.connect=lambda *args,**kwargs:original(*args,**dict(kwargs,factory=Connection))
sys.argv=['app.archive_admin',*sys.argv[1:]]
runpy.run_module('app.archive_admin',run_name='__main__')
'''
        crashed = subprocess.run([sys.executable,'-B','-c',script,*command[4:]],
            env=dict(environment,CRASH_PHASE=config['scenario']),capture_output=True,timeout=25)
        assert crashed.returncode == (71 if config['scenario']=='commit-before' else 72),crashed.stderr.decode()
        assert not crashed.stdout and not crashed.stderr
        with sqlite3.connect('/tmp/source.db') as db:
            assert db.execute('SELECT count(*) FROM security_audit_isolated_recoveries').fetchone() == (
                0 if config['scenario']=='commit-before' else 1,)
    # Missing credentials fail safely without including secret material in CLI diagnostics.
    denied = subprocess.run(command,env={k:v for k,v in environment.items() if k!='ATOM_BROKER_ADMIN_TOKEN'},
                            capture_output=True,timeout=10)
    assert denied.returncode == 1 and not denied.stderr
    assert json.loads(denied.stdout) == {'ok':False,'error':'invalid_broker_client_configuration'}
    first = subprocess.run(command,env=environment,capture_output=True,timeout=25)
    assert first.returncode == 0 and not first.stderr,first.stderr.decode()
    response = json.loads(first.stdout)
    assert response['ok'] and response['receipt']['protocol']=='audit-recovery-v2'
    assert not response['deletion_authorized'] and 'events' not in response
    replay = subprocess.run(command,env=environment,capture_output=True,timeout=10)
    assert replay.returncode == 0 and replay.stdout == first.stdout and not replay.stderr
    assert config['token'].encode() not in first.stdout+denied.stdout
    inspection = owner.inspect(archive_id='archive')
    assert inspection['isolated_recovery_receipts']==1 and inspection['recovery_receipts']==0
    return 1


try:
    count = run_cli() if config['scenario'] in ('cli','commit-before','commit-after') else asyncio.run(run())
    print(json.dumps({'scenario':config['scenario'],'receipts':count}))
finally:
    relay.shutdown()
    relay.server_close()
    thread.join(5)
