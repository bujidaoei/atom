"""Executed inside a real Linux container against a copied actual business fixture."""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import subprocess
from unittest.mock import patch

from app.audit_archiving import AuditArchiving
from app.audit_archive import ArchiveError
from app.audit_retention import RetentionError

shutil.copyfile('/seed.db', '/tmp/source.db')
os.chmod('/tmp/source.db', 0o600)
Path('/tmp/archive').mkdir(mode=0o700)
service = AuditArchiving(Path('/tmp/source.db'), store_id=sys.argv[2], root=Path('/tmp/archive'))
request = dict(archive_id='archive',operator_id='operator',policy_id='policy',expected_generation=1)


def counts():
    with sqlite3.connect('/tmp/source.db') as db:
        return tuple(db.execute('SELECT count(*) FROM '+table).fetchone()[0]
            for table in ('security_audit_archives','security_audit_archive_recoveries'))


scenario = sys.argv[1]
if scenario in ('cli','pages','pages-hold'):
    def cli(operation, **values):
        command = [sys.executable,'-B','-m','app.archive_admin','--database','/tmp/source.db',
            '--store-id',sys.argv[2],'--store-root','/tmp/archive',operation]
        for key,value in values.items():
            if value is not None: command += ['--'+key.replace('_','-'),str(value)]
        result = subprocess.run(command,capture_output=True,timeout=15)
        assert not result.stderr, result.stderr.decode()
        return result.returncode,json.loads(result.stdout)
    status, first = cli('archive',**request)
    assert status == 0 and first['ok'] and not first['deletion_authorized']
    assert 'events' not in first and first['recovery_receipts'] == 0
    assert cli('archive',**request) == (status,first)
    status, recovered = cli('recover',archive_id='archive',recovery_id='recovery',verifier_id='verifier')
    assert status == 0 and recovered['receipt']['event_count'] == first['archive']['event_count']
    status, inspected = cli('inspect',archive_id='archive')
    assert status == 0 and inspected['recovery_receipts'] == 1
    if scenario == 'pages-hold':
        service.repository.execute(command_id='page-hold',policy_id='policy',operator_id='operator',
            action='place_hold',expected_generation=1,hold_id='page-hold',hold_kind='operational')
        status, failure = cli('archive',archive_id='second',operator_id='operator',**first['continuation'])
        assert status == 1 and failure['error'] == 'retention_generation_conflict'
        assert counts() == (1,1)
    elif scenario == 'pages':
        assert first['archive']['event_count'] == 100 and first['continuation']
        status, second = cli('archive',archive_id='second',operator_id='operator',**first['continuation'])
        assert status == 0 and second['archive']['event_count'] == 2 and second['continuation'] is None
        assert second['archive']['after_sequence'] == first['last_sequence']
        assert second['last_sequence'] == first['archive']['upper_sequence']
        assert counts() == (2,1)
    else:
        assert first['continuation'] is None
        status, failure = cli('archive',**dict(request,operator_id='changed'))
        assert status == 1 and failure == {'ok':False,'error':'archive_identity_conflict'}
        status, failure = cli('inspect',archive_id='missing')
        assert status == 1 and failure == {'ok':False,'error':'archive_not_found'}
elif scenario in ('hold','receiver'):
    original = service.store.put
    def change(*args, **kwargs):
        result = original(*args, **kwargs)
        if scenario == 'hold':
            service.repository.execute(command_id='new-hold',policy_id='policy',operator_id='operator',
                action='place_hold',expected_generation=1,hold_id='hold',hold_kind='legal')
        else:
            # Registry9 operator integration is separate; this probes constrained SQL context change.
            with sqlite3.connect('/tmp/source.db') as db:
                db.execute("INSERT INTO security_audit_destinations(destination_id,scope_kind,scope_id,generation,state,created_at,updated_at) VALUES ('new','account','user',1,'unconfigured',100,100)")
        return result
    with patch.object(service.store, 'put', change):
        try: service.archive(**request)
        except RetentionError: pass
        else: raise AssertionError('stale context registered')
    assert counts() == (0,0) and len(list(Path('/tmp/archive').glob('*.atomaudit'))) == 1
elif scenario == 'corrupt':
    registered = service.archive(**request)
    file = Path('/tmp/archive')/(registered['archive_sha256']+'.atomaudit')
    file.chmod(0o600)
    file.write_bytes(b'corrupt')
    try: service.recover(archive_id='archive',recovery_id='recover',verifier_id='verifier')
    except ArchiveError: pass
    else: raise AssertionError('corrupt recovery accepted')
    assert counts() == (1,0)
elif scenario.startswith('crash-'):
    _, action, phase = scenario.split('-')
    if action == 'recover': service.archive(**request)
    pid = os.fork()
    if pid == 0:
        original = sqlite3.connect
        class Connection(sqlite3.Connection):
            wrote = False
            def execute(self, sql, *args, **kwargs):
                if sql.startswith('INSERT INTO security_audit_archive'): self.wrote = True
                if sql == 'COMMIT' and self.wrote and phase == 'before': os._exit(71)
                result = super().execute(sql,*args,**kwargs)
                if sql == 'COMMIT' and self.wrote and phase == 'after': os._exit(72)
                return result
        with patch('sqlite3.connect', lambda *args,**kwargs: original(*args,**dict(kwargs,factory=Connection))):
            if action == 'archive': service.archive(**request)
            else: service.recover(archive_id='archive',recovery_id='recover',verifier_id='verifier')
        os._exit(73)
    assert os.waitstatus_to_exitcode(os.waitpid(pid,0)[1]) == (71 if phase == 'before' else 72)
    assert counts() == ((int(phase=='after'),0) if action=='archive' else (1,int(phase=='after')))
    reopened = AuditArchiving(Path('/tmp/source.db'),store_id=sys.argv[2],root=Path('/tmp/archive'))
    reopened.archive(**request)
    reopened.recover(archive_id='archive',recovery_id='recover',verifier_id='verifier')
    assert counts() == (1,1)
else:
    first = service.archive(**request)
    assert first['event_count'] == 3 and counts() == (1,0)
    assert service.archive(**request) == first
    receipt = service.recover(archive_id='archive',recovery_id='recover',verifier_id='verifier')
    assert receipt == service.recover(archive_id='archive',recovery_id='recover',verifier_id='verifier')
    assert counts() == (1,1)
    try: service.archive(**dict(request,operator_id='other'))
    except ArchiveError: pass
    else: raise AssertionError('identity conflict accepted')
print(json.dumps({'scenario':scenario,'counts':counts()}))
