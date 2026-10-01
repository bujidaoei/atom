"""Adversarial worker stdout cannot change the dispatched verification scope."""
import hashlib
import json
import time

import pytest

from app.artifacts import Artifact
from app.verification_contract import capture_contract, capture_report
from app.verification_repository import VerificationRequest
from app.verifier_authority import VerifierAssignment
from app.verifier_supervisor import SupervisorError, _decode


@pytest.fixture
def evidence():
    contract = capture_contract([{'key': 'page', 'title': 'Page', 'detail': '',
                                  'checks': [{'type': 'exists', 'selector': 'body'}]}])
    now = int(time.time())
    request = VerificationRequest('request', 'workspace', 'project', 'revision', contract,
                                  'c' * 64, 'runner', 'user', now, now + 60)
    assignment = VerifierAssignment(request, Artifact('a' * 64, 'b' * 64, 123),
                                    'd' * 32, 'worker', 'e' * 64, b'0' * 32)
    report = capture_report(contract, [
        {'key': 'page', 'checkIndex': 0, 'passed': True, 'note': 'observed'}])
    document = {'format': 'atom-verifier-observation-v1', 'routeId': assignment.route_id,
                'artifactKey': assignment.artifact.key,
                'snapshotRevision': assignment.artifact.revision,
                'artifactSize': assignment.artifact.size,
                'contractDigest': contract.digest,
                'reportDigest': hashlib.sha256(report.canonical).hexdigest(),
                'report': json.loads(report.canonical)}
    return assignment, document


def _wire(document):
    return json.dumps(document, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':')).encode() + b'\n'


def test_only_exact_canonical_report_is_admitted(evidence):
    assignment, document = evidence
    assert _decode(_wire(document), assignment) == [
        {'key': 'page', 'checkIndex': 0, 'passed': True, 'note': 'observed'}]
    for change in ({'routeId': 'f' * 32}, {'artifactKey': 'f' * 64},
                   {'snapshotRevision': 'f' * 64}, {'artifactSize': 124},
                   {'contractDigest': 'f' * 64}, {'reportDigest': 'f' * 64},
                   {'unexpected': 1}):
        with pytest.raises(SupervisorError):
            _decode(_wire(document | change), assignment)


def test_duplicate_noncanonical_and_incomplete_reports_are_rejected(evidence):
    assignment, document = evidence
    raw = _wire(document)
    for forged in (raw[:-2] + b',"routeId":"' + b'd' * 32 + b'"}\n',
                   b' ' + raw, raw + b'{}', raw.replace(b'"passed":true', b'"passed":false')):
        with pytest.raises(SupervisorError):
            _decode(forged, assignment)
    missing = dict(document)
    missing['report'] = dict(document['report']) | {'results': []}
    with pytest.raises(SupervisorError):
        _decode(_wire(missing), assignment)
