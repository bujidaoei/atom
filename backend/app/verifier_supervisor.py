"""Trusted host-side owner for one isolated browser verification container.

The coordinator keeps the one-use database credential. The untrusted browser
container receives only the pinned artifact/contract job, and its report is
registered only after exact process exit and canonical output validation.
"""
import hashlib
import hmac
import io
import json
from pathlib import Path
import re
import secrets
import struct
import time
from typing import Callable

from .artifacts import ArtifactError
from .sandbox.docker_driver import DriverError, run_bounded, run_verifier_bounded
from .snapshots import MAX_ARCHIVE_BYTES, SnapshotError, verify_snapshot
from .verification_contract import ContractError, MAX_BYTES, load_contract, load_report
from .verifier_authority import VerifierAssignment, VerifierAuthority


_IMAGE = re.compile(r'sha256:[0-9a-f]{64}\Z')
_VERIFIER = re.compile(r'[A-Za-z0-9_.-]{1,128}\Z')
_CONTAINER = re.compile(r'[0-9a-f]{64}\Z')
_OWN_NAME = re.compile(r'/atom-verifier-[0-9a-f]{32}\Z')
_OUTPUT_LIMIT = MAX_BYTES + 2048
_PROFILE = {'memoryBytes': 1 << 30, 'shmBytes': 256 << 20,
            'tmpBytes': 128 << 20, 'nanoCpus': 1_500_000_000,
            'pids': 128, 'capAdd': ['SYS_CHROOT'], 'network': 'none'}


class SupervisorError(RuntimeError):
    pass


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SupervisorError('invalid_worker_output')
        result[key] = value
    return result


def _decode(raw: bytes, assignment: VerifierAssignment):
    if not raw.endswith(b'\n') or raw.count(b'\n') != 1 or len(raw) > _OUTPUT_LIMIT:
        raise SupervisorError('invalid_worker_output')
    try:
        document = json.loads(raw[:-1].decode('utf-8'), object_pairs_hook=_unique)
    except (ValueError, UnicodeError, RecursionError):
        raise SupervisorError('invalid_worker_output') from None
    if type(document) is not dict or set(document) != {
            'format', 'routeId', 'artifactKey', 'snapshotRevision', 'artifactSize',
            'contractDigest', 'reportDigest', 'report'}:
        raise SupervisorError('invalid_worker_output')
    if (document['format'] != 'atom-verifier-observation-v1'
            or document['routeId'] != assignment.route_id
            or document['artifactKey'] != assignment.artifact.key
            or document['snapshotRevision'] != assignment.artifact.revision
            or document['artifactSize'] != assignment.artifact.size
            or document['contractDigest'] != assignment.request.contract.digest
            or type(document['reportDigest']) is not str
            or re.fullmatch(r'[0-9a-f]{64}', document['reportDigest']) is None):
        raise SupervisorError('worker_scope_mismatch')
    try:
        encoded_report = json.dumps(document['report'], ensure_ascii=False,
                                    sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode('utf-8')
        report = load_report(assignment.request.contract, encoded_report)
    except (ContractError, TypeError, ValueError, UnicodeError):
        raise SupervisorError('invalid_worker_output') from None
    if not hmac.compare_digest(hashlib.sha256(report.canonical).hexdigest(),
                               document['reportDigest']):
        raise SupervisorError('worker_report_mismatch')
    canonical = json.dumps(document, ensure_ascii=False, sort_keys=True,
                           separators=(',', ':'), allow_nan=False).encode('utf-8')
    if canonical != raw[:-1]:
        raise SupervisorError('invalid_worker_output')
    return json.loads(report.canonical)['results']


class VerifierSupervisor:
    def __init__(self, *, image: str, seccomp_path: Path, verifier_id: str,
                 executable: str = 'docker'):
        if (type(image) is not str or _IMAGE.fullmatch(image) is None
                or type(verifier_id) is not str or _VERIFIER.fullmatch(verifier_id) is None
                or type(executable) is not str or not executable):
            raise SupervisorError('invalid_supervisor_configuration')
        path = Path(seccomp_path)
        if not path.is_absolute() or not path.is_file():
            raise SupervisorError('invalid_supervisor_configuration')
        profile = path.read_bytes()
        if not 0 < len(profile) <= 65536:
            raise SupervisorError('invalid_supervisor_configuration')
        try:
            policy = json.loads(profile)
            if type(policy) is not dict or policy.get('defaultAction') != 'SCMP_ACT_ERRNO':
                raise ValueError
        except (ValueError, UnicodeError):
            raise SupervisorError('invalid_supervisor_configuration') from None
        self.image, self.seccomp_path = image, path
        self.verifier_id, self.executable = verifier_id, executable
        self._profile_digest = hashlib.sha256(profile).hexdigest()
        encoded = json.dumps({'image': image, 'seccomp': self._profile_digest,
                              'profile': _PROFILE, 'worker': 'atom-verifier-observation-v1'},
                             sort_keys=True, separators=(',', ':')).encode()
        self.environment_digest = hashlib.sha256(encoded).hexdigest()

    def _image(self):
        try:
            status, raw, _ = run_bounded([self.executable, 'image', 'inspect', self.image],
                                         output_limit=16384)
            value = json.loads(raw)
            if (status != 0 or type(value) is not list or len(value) != 1
                    or value[0]['Id'] != self.image
                    or value[0]['Config']['User'] != '10001:10001'
                    or value[0]['Config'].get('Volumes')):
                raise ValueError
        except (DriverError, ValueError, KeyError, TypeError):
            raise SupervisorError('verifier_image_unavailable') from None

    def _cleanup(self, name: str):
        try:
            run_bounded([self.executable, 'container', 'rm', '--force', name], timeout=10)
            status, raw, _ = run_bounded([self.executable, 'container', 'ls', '--all',
                '--filter', f'name=^/{name}$', '--format', '{{.Names}}'], timeout=10)
            if status != 0 or raw.strip():
                raise SupervisorError('verifier_termination_unknown')
        except DriverError:
            raise SupervisorError('verifier_termination_unknown') from None

    def _owned_ids(self):
        try:
            status, raw, _ = run_bounded([self.executable, 'container', 'ls', '--all',
                '--quiet', '--no-trunc', '--filter',
                f'label=atom.verifier.owner={self.verifier_id}', '--filter',
                'label=atom.verifier.protocol=v1'], timeout=10, output_limit=8192)
            if status != 0:
                raise SupervisorError('verifier_inventory_unknown')
            rows = raw.decode('ascii').splitlines()
            if len(rows) > 100 or any(_CONTAINER.fullmatch(row) is None for row in rows):
                raise SupervisorError('verifier_inventory_unknown')
            return rows
        except (DriverError, UnicodeError):
            raise SupervisorError('verifier_inventory_unknown') from None

    def reap_orphans(self, *, lease_guard: Callable[[], None] | None = None):
        """Cold-start operation; a live coordinator supplies its lease guard."""
        if lease_guard is not None:
            lease_guard()
        identities = self._owned_ids()
        for identity in identities:
            if lease_guard is not None:
                lease_guard()
            try:
                status, raw, _ = run_bounded([self.executable, 'container', 'inspect',
                    '--format', '{{json .Config.Labels}}|{{.Name}}|{{.Image}}', identity],
                    timeout=10, output_limit=8192)
                if status != 0:
                    raise SupervisorError('verifier_inventory_unknown')
                fields = raw.decode('utf-8').strip().split('|')
                if len(fields) != 3:
                    raise ValueError
                labels = json.loads(fields[0])
                name, image = fields[1:]
                if (type(labels) is not dict or _OWN_NAME.fullmatch(name) is None
                        or _IMAGE.fullmatch(image) is None
                        or labels.get('atom.verifier.protocol') != 'v1'
                        or labels.get('atom.verifier.owner') != self.verifier_id
                        or _VERIFIER.fullmatch(labels.get('atom.verifier.request', '')) is None
                        or re.fullmatch(r'[0-9a-f]{32}', labels.get('atom.verifier.route', '')) is None
                        or labels.get('atom.verifier.image') != image):
                    raise ValueError
            except (DriverError, UnicodeError, ValueError, TypeError):
                raise SupervisorError('verifier_inventory_unknown') from None
            if lease_guard is not None:
                lease_guard()
            self._cleanup(name[1:])
        if lease_guard is not None:
            lease_guard()
        if self._owned_ids():
            raise SupervisorError('verifier_termination_unknown')
        return len(identities)

    def verify_and_register(self, *, assignment: VerifierAssignment, store,
                            authority: VerifierAuthority, budget_seconds: int = 30,
                            lease_guard: Callable[[], None] | None = None):
        if lease_guard is not None:
            lease_guard()
        if (type(assignment) is not VerifierAssignment or type(authority) is not VerifierAuthority
                or assignment.verifier_id != self.verifier_id
                or assignment.environment_digest != self.environment_digest
                or type(budget_seconds) is not int or not 1 <= budget_seconds <= 300):
            raise SupervisorError('worker_scope_mismatch')
        try:
            current_profile = self.seccomp_path.read_bytes()
        except OSError:
            raise SupervisorError('verifier_policy_unavailable') from None
        if hashlib.sha256(current_profile).hexdigest() != self._profile_digest:
            raise SupervisorError('verifier_policy_changed')
        available = int(assignment.request.deadline - time.time())
        if available < 10:
            raise SupervisorError('verification_expired')
        budget = min(budget_seconds, available - 8)
        try:
            payload = store.read(assignment.artifact.key)
            if (type(payload) is not bytes or len(payload) != assignment.artifact.size
                    or hashlib.sha256(payload).hexdigest() != assignment.artifact.key
                    or verify_snapshot(io.BytesIO(payload)).revision != assignment.artifact.revision):
                raise SupervisorError('verifier_artifact_mismatch')
            contract = load_contract(assignment.request.contract.canonical)
        except (ArtifactError, SnapshotError, ContractError, OSError, ValueError):
            raise SupervisorError('verifier_artifact_mismatch') from None
        if contract.digest != assignment.request.contract.digest:
            raise SupervisorError('worker_scope_mismatch')
        if lease_guard is not None:
            lease_guard()
        self._image()
        job = {'routeId': assignment.route_id, 'artifactKey': assignment.artifact.key,
               'snapshotRevision': assignment.artifact.revision,
               'artifactSize': assignment.artifact.size,
               'contractDigest': contract.digest, 'budgetSeconds': budget}
        fields = (json.dumps(job, sort_keys=True, separators=(',', ':')).encode(),
                  contract.canonical, payload)
        wire = b''.join(struct.pack('>I', len(field)) + field for field in fields)
        name = 'atom-verifier-' + secrets.token_hex(16)
        command = [self.executable, 'run', '--rm', '--init', '--name', name,
            '--pull', 'never', '--network', 'none', '--read-only',
            '--tmpfs', '/tmp:rw,nosuid,nodev,size=128m,uid=10001,gid=10001,mode=0700',
            '--shm-size', '256m', '--memory', '1g', '--memory-swap', '1g',
            '--cpus', '1.5', '--pids-limit', '128', '--cap-drop', 'ALL',
            '--cap-add', 'SYS_CHROOT', '--security-opt', 'no-new-privileges',
            '--security-opt', f'seccomp={self.seccomp_path}', '--user', '10001:10001',
            '--label', 'atom.verifier.protocol=v1',
            '--label', f'atom.verifier.owner={self.verifier_id}',
            '--label', f'atom.verifier.image={self.image}',
            '--label', f'atom.verifier.request={assignment.request.id}',
            '--label', f'atom.verifier.route={assignment.route_id}', '-i', self.image]
        try:
            try:
                status, output, _ = run_verifier_bounded(command,
                    timeout=min(budget + 8, available), output_limit=_OUTPUT_LIMIT,
                    input_data=wire)
            except DriverError:
                raise SupervisorError('verifier_execution_failed') from None
            if status != 0:
                raise SupervisorError('verifier_execution_failed')
            results = _decode(output, assignment)
        finally:
            if lease_guard is not None:
                lease_guard()
            self._cleanup(name)
        if lease_guard is not None:
            lease_guard()
        return authority.register(request_id=assignment.request.id, route_id=assignment.route_id,
            verifier_id=assignment.verifier_id,
            environment_digest=assignment.environment_digest,
            artifact=assignment.artifact, credential=assignment.credential, results=results)
