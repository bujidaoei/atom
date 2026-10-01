"""Strict, versioned identities for verifier inputs and complete result sets.

These codecs validate content, not the authority or honesty of its producer.
"""
from dataclasses import dataclass
import hashlib
import json
import re

MAX_BYTES = 1_048_576
MAX_REQUIREMENTS = 128
MAX_CHECKS = 512
FORMAT = 'atom-verification-contract-v1'


class ContractError(ValueError):
    pass


def _fail():
    raise ContractError('invalid_verification_contract')


def _text(value, limit, *, empty=False):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()) or '\0' in value:
        _fail()
    try:
        value.encode('utf-8', errors='strict')
    except UnicodeError:
        _fail()
    return value


def _object(value, required, optional=()):
    if type(value) is not dict or not set(required) <= value.keys() or value.keys() - set(required) - set(optional):
        _fail()


def _encode(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    if len(encoded) > MAX_BYTES:
        _fail()
    return encoded


def _step(value):
    if type(value) is not dict:
        _fail()
    action = value.get('action')
    if action not in ('fill', 'click', 'press'):
        _fail()
    fields = ('action', 'selector') + (('value',) if action == 'fill' else ('key',) if action == 'press' else ())
    _object(value, fields)
    result = {'action': action, 'selector': _text(value['selector'], 1000)}
    if action == 'fill':
        result['value'] = _text(value['value'], 2000, empty=True)
    if action == 'press':
        key = _text(value['key'], 20)
        if not (len(key) == 1 and key.isprintable() or key in (
            'Enter', 'Escape', 'Tab', 'Backspace', 'Delete', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Home', 'End')):
            _fail()
        result['key'] = key
    return result


def _check(value):
    if type(value) is not dict:
        _fail()
    kind = value.get('type')
    if kind not in ('exists', 'text', 'flow'):
        _fail()
    fields = ('type', 'selector') + (('contains',) if kind == 'text' else ('expect',) if kind == 'flow' else ())
    _object(value, fields, ('setup',) if kind == 'flow' else ())
    result = {'type': kind, 'selector': _text(value['selector'], 1000)}
    if kind == 'text':
        result['contains'] = _text(value['contains'], 2000)
    if kind == 'flow':
        result['expect'] = _text(value['expect'], 1000)
        setup = value.get('setup', [])
        if type(setup) is not list or len(setup) > 12:
            _fail()
        result['setup'] = [_step(step) for step in setup]
    return result


@dataclass(frozen=True)
class VerificationContract:
    canonical: bytes
    digest: str
    checks: tuple[tuple[str, int], ...]


def capture_contract(requirements) -> VerificationContract:
    if type(requirements) is not list or not 1 <= len(requirements) <= MAX_REQUIREMENTS:
        _fail()
    rows, identities, seen = [], [], set()
    for item in requirements:
        _object(item, ('key', 'title', 'detail', 'checks'))
        key = _text(item['key'], 80)
        if re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', key) is None or key in seen:
            _fail()
        seen.add(key)
        checks = item['checks']
        if type(checks) is not list or not 1 <= len(checks) <= 32 or len(identities) + len(checks) > MAX_CHECKS:
            _fail()
        rows.append({'key': key, 'title': _text(item['title'], 200),
                     'detail': _text(item['detail'], 1000, empty=True), 'checks': [_check(c) for c in checks]})
        identities.extend((key, index) for index in range(len(checks)))
    canonical = _encode({'format': FORMAT, 'requirements': rows})
    return VerificationContract(canonical, hashlib.sha256(canonical).hexdigest(), tuple(identities))


def load_contract(raw: bytes) -> VerificationContract:
    if type(raw) is not bytes or len(raw) > MAX_BYTES:
        _fail()
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                _fail()
            result[key] = value
        return result
    try:
        document = json.loads(raw.decode('utf-8'), object_pairs_hook=unique)
    except (UnicodeError, ValueError, RecursionError):
        _fail()
    _object(document, ('format', 'requirements'))
    if document['format'] != FORMAT:
        _fail()
    return capture_contract(document['requirements'])


@dataclass(frozen=True)
class VerificationReport:
    canonical: bytes
    total: int
    passed: int


def capture_report(contract: VerificationContract, results) -> VerificationReport:
    # Re-derive identities from the stored bytes, not caller-constructed fields.
    contract = load_contract(contract.canonical)
    if type(results) is not list or len(results) != len(contract.checks):
        _fail()
    expected, collected = set(contract.checks), {}
    for item in results:
        _object(item, ('key', 'checkIndex', 'passed', 'note'))
        key = _text(item['key'], 80)
        index = item['checkIndex']
        if type(index) is not int or type(item['passed']) is not bool:
            _fail()
        identity = (key, index)
        if identity not in expected or identity in collected:
            _fail()
        collected[identity] = {'key': key, 'checkIndex': index, 'passed': item['passed'],
                               'note': _text(item['note'], 2000, empty=True)}
    ordered = [collected[identity] for identity in contract.checks]
    return VerificationReport(_encode({'format': 'atom-verification-report-v1',
        'contractDigest': contract.digest, 'results': ordered}), len(ordered), sum(item['passed'] for item in ordered))


def load_report(contract: VerificationContract, raw: bytes) -> VerificationReport:
    """Reject noncanonical, incomplete or identity-swapped stored evidence."""
    if type(raw) is not bytes or len(raw) > MAX_BYTES:
        _fail()
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                _fail()
            result[key] = value
        return result
    try:
        document = json.loads(raw.decode('utf-8'), object_pairs_hook=unique)
    except (UnicodeError, ValueError, RecursionError):
        _fail()
    _object(document, ('format', 'contractDigest', 'results'))
    if document['format'] != 'atom-verification-report-v1' or document['contractDigest'] != contract.digest:
        _fail()
    report = capture_report(contract, document['results'])
    if report.canonical != raw:
        _fail()
    return report
