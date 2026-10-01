"""Single-use browser worker for a supervisor-owned isolated container.

The worker has no database, provider key, Docker socket or publication route.
Its stdout is an observation, never authority to register or publish.
"""
import hashlib
import json
import re
import struct
import sys

from playwright.sync_api import Error as BrowserError, sync_playwright

from .artifacts import Artifact
from .snapshots import MAX_ARCHIVE_BYTES
from .verification_contract import ContractError, MAX_BYTES, load_contract
from .verification_observer import ObservationError, observe_contract
from .verification_origin import pinned_snapshot_origin


_DIGEST = re.compile(r'[0-9a-f]{64}\Z')
_ROUTE = re.compile(r'[0-9a-f]{32}\Z')
class WorkerError(ValueError):
    pass


def _read_exact(stream, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = stream.read(min(65536, size - len(chunks)))
        if not isinstance(chunk, bytes) or not chunk or len(chunk) > size - len(chunks):
            raise WorkerError('invalid_worker_input')
        chunks.extend(chunk)
    return bytes(chunks)


def _frame(stream, limit: int) -> bytes:
    size = struct.unpack('>I', _read_exact(stream, 4))[0]
    if not 0 < size <= limit:
        raise WorkerError('invalid_worker_input')
    return _read_exact(stream, size)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise WorkerError('invalid_worker_job')
        result[key] = value
    return result


def _job(raw: bytes):
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique)
    except (ValueError, UnicodeError, RecursionError):
        raise WorkerError('invalid_worker_job') from None
    if type(value) is not dict or set(value) != {'routeId', 'artifactKey', 'snapshotRevision',
                                                  'artifactSize', 'contractDigest', 'budgetSeconds'}:
        raise WorkerError('invalid_worker_job')
    if (type(value['routeId']) is not str or not _ROUTE.fullmatch(value['routeId'])
            or any(type(value[name]) is not str or not _DIGEST.fullmatch(value[name])
                   for name in ('artifactKey', 'snapshotRevision', 'contractDigest'))
            or type(value['artifactSize']) is not int or not 0 < value['artifactSize'] <= MAX_ARCHIVE_BYTES
            or type(value['budgetSeconds']) is not int or not 0 < value['budgetSeconds'] <= 300):
        raise WorkerError('invalid_worker_job')
    return value


def run(stream=None) -> bytes:
    """Return a bounded canonical observation envelope after actual Chromium IO."""
    stream = sys.stdin.buffer if stream is None else stream
    job = _job(_frame(stream, 2048))
    contract = load_contract(_frame(stream, MAX_BYTES))
    if contract.digest != job['contractDigest']:
        raise WorkerError('worker_contract_mismatch')
    artifact = Artifact(job['artifactKey'], job['snapshotRevision'], job['artifactSize'])
    payload = _frame(stream, MAX_ARCHIVE_BYTES)
    if len(payload) != artifact.size or stream.read(1) != b'':
        raise WorkerError('invalid_worker_input')
    with pinned_snapshot_origin(payload, artifact) as url:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(chromium_sandbox=True)
            try:
                report = observe_contract(browser, contract, url,
                                          budget_seconds=job['budgetSeconds'])
            finally:
                browser.close()
    envelope = {'format': 'atom-verifier-observation-v1', 'routeId': job['routeId'],
                'artifactKey': artifact.key, 'snapshotRevision': artifact.revision,
                'artifactSize': artifact.size, 'contractDigest': contract.digest,
                'reportDigest': hashlib.sha256(report.canonical).hexdigest(),
                'report': json.loads(report.canonical)}
    encoded = json.dumps(envelope, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':')).encode('utf-8')
    if len(encoded) > MAX_BYTES + 2048:
        raise WorkerError('worker_report_too_large')
    return encoded


def main() -> int:
    try:
        result = run()
    except (WorkerError, ContractError, ObservationError, BrowserError, OSError, ValueError):
        # Do not print the contract, snapshot, browser URL or secrets to logs.
        print('verifier_worker_failed', file=sys.stderr)
        return 1
    sys.stdout.buffer.write(result + b'\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
