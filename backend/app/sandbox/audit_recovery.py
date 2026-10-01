"""Fixed standard-library recovery program for a fresh broker-owned container."""
import json
from pathlib import Path
import time

from ..audit_archive import ArchiveError, MAX_ARCHIVE_BYTES, decode_archive
from .docker_driver import DriverError, run_bounded


_ROOT = Path(__file__).parents[1]
_SOURCES = {name: (_ROOT/(name+'.py')).read_text(encoding='utf-8') for name in ('audit_event_format','audit_archive')}
_PROGRAM = """
import json,signal,sys,types
def deadline(*_):raise TimeoutError('recovery_timeout')
signal.signal(signal.SIGALRM,deadline)
signal.alarm(15)
package=types.ModuleType('app');package.__path__=[];sys.modules['app']=package
sources=TRUSTED_SOURCES
for name in ('audit_event_format','audit_archive'):
    module=types.ModuleType('app.'+name);sys.modules[module.__name__]=module
    exec(compile(sources[name],name+'.py','exec'),module.__dict__)
try:
    data=sys.stdin.buffer.read(262144+66)
    if len(data)>262144+65 or data[64:65]!=b'\\n':raise ValueError('invalid_input')
    result=sys.modules['app.audit_archive'].recover_archive(data[65:],expected_sha256=data[:64].decode('ascii'))
    output=json.dumps(result,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('ascii')
    if len(output)>263168:raise ValueError('output_limit')
    sys.stdout.buffer.write(output);sys.stdout.buffer.flush()
except Exception:
    sys.exit(2)
finally:
    signal.alarm(0)
""".replace('TRUSTED_SOURCES', repr(_SOURCES))


class AuditRecoveryOperations:
    def __init__(self, driver):
        self.driver = driver

    def execute(self, attempt, payload, *, expected_sha256):
        expected = decode_archive(payload, expected_sha256=expected_sha256)
        if attempt.state != 'provisioning' or attempt.deadline <= time.time():
            raise ArchiveError('recovery_attempt_not_fresh')
        state = self.driver.inspect(attempt)
        if state is None or not state.running or state.paused:
            raise ArchiveError('recovery_worker_unavailable')
        status, output, _ = run_bounded([self.driver.executable,'container','exec','--interactive',state.id,
            '/usr/local/bin/python3','-I','-c',_PROGRAM], input_data=expected_sha256.encode('ascii')+b'\n'+payload,
            timeout=20,output_limit=MAX_ARCHIVE_BYTES+1024)
        if status != 0:
            raise DriverError('archive_recovery_failed')
        try:
            result = json.loads(output)
            wanted = dict(archive_sha256=expected_sha256,manifest=expected['manifest'],events=expected['events'],
                recovery_target='isolated_memory_database',deletion_authorized=False)
            if output != json.dumps(wanted,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('ascii'):
                raise ValueError
        except (ValueError,TypeError,RecursionError):
            raise DriverError('invalid_archive_recovery_result') from None
        return result
