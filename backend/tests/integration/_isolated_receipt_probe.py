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
import sys
import threading

from app.audit_archiving import AuditArchiving
from app.audit_archive import ArchiveError
from app.sandbox.audit_recovery_client import AuditRecoveryClient
from app.sandbox.client import BrokerClientError

config = json.load(sys.stdin)
shutil.copyfile('/seed.db', '/tmp/source.db')
os.chmod('/tmp/source.db', 0o600)
Path('/tmp/archive').mkdir(mode=0o700)
with sqlite3.connect('/tmp/source.db') as db:
    store = db.execute('SELECT archive_store_id FROM security_audit_retention_policies').fetchone()[0]
owner = AuditArchiving(Path('/tmp/source.db'),store_id=store,root=Path('/tmp/archive'))
owner.archive(archive_id='archive',operator_id='operator',policy_id='policy',expected_generation=1)
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
        if scenario in ('auth','policy','lost-result','worker','cancelled'):
            try: await owner.recover_isolated(**request,client=client)
            except (BrokerClientError, asyncio.CancelledError): pass
            else: raise AssertionError('failed verification issued receipt')
            expected = 0
        else:
            receipt = await owner.recover_isolated(**request,client=client)
            assert receipt['protocol'] == 'audit-recovery-v2'
            assert receipt['result_sha256'] == hashlib.sha256(json.dumps(seen[0],sort_keys=True,
                separators=(',',':'),ensure_ascii=True).encode()).hexdigest()
            assert await owner.recover_isolated(**request,client=client) == receipt
            assert len(seen) == 1
            try: await owner.recover_isolated(**dict(request,verifier_id='different'),client=client)
            except ArchiveError as error: assert str(error) == 'recovery_identity_conflict'
            else: raise AssertionError('identity conflict accepted')
            expected = 1
        try: owner.recover(**request)
        except ArchiveError as error: assert str(error) == 'isolated_recovery_required'
        else: raise AssertionError('legacy receipt accepted on schema10')
        with sqlite3.connect('/tmp/source.db') as db:
            assert db.execute('SELECT count(*) FROM security_audit_isolated_recoveries').fetchone() == (expected,)
            assert db.execute('SELECT count(*) FROM security_audit_archive_recoveries').fetchone() == (0,)
        inspection = owner.inspect(archive_id='archive')
        assert inspection['isolated_recovery_receipts'] == expected
        assert inspection['recovery_receipts'] == 0 and not inspection['deletion_authorized']
    return expected


try:
    count = asyncio.run(run())
    print(json.dumps({'scenario':config['scenario'],'receipts':count}))
finally:
    relay.shutdown()
    relay.server_close()
    thread.join(5)
