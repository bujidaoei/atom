import copy
import hashlib
import json

import pytest

from app.verification_contract import ContractError, capture_contract, capture_report, load_contract, load_report


def requirements():
    return [{'key': 'submit', 'title': '提交', 'detail': '', 'checks': [
        {'type': 'exists', 'selector': '#name'},
        {'type': 'flow', 'selector': '#submit', 'expect': '#success',
         'setup': [{'action': 'fill', 'selector': '#name', 'value': ' Alice '},
                   {'action': 'press', 'selector': '#name', 'key': 'Enter'}]}]}]


def test_format_one_has_fixed_canonical_encoding():
    contract = capture_contract([{'key': 'a', 'title': 'A', 'detail': '',
                                  'checks': [{'type': 'exists', 'selector': '#a'}]}])
    expected = b'{"format":"atom-verification-contract-v1","requirements":[{"checks":[{"selector":"#a","type":"exists"}],"detail":"","key":"a","title":"A"}]}'
    assert contract.canonical == expected
    assert contract.digest == hashlib.sha256(expected).hexdigest()


def test_canonical_bytes_roundtrip_order_and_detachment():
    source = requirements()
    captured = capture_contract(source)
    assert captured.digest == hashlib.sha256(captured.canonical).hexdigest()
    assert load_contract(captured.canonical) == captured
    assert captured.checks == (('submit', 0), ('submit', 1))
    reordered = [dict(reversed(list(source[0].items())))]
    assert capture_contract(reordered) == captured
    source[0]['checks'][1]['setup'][0]['value'] = 'Bob'
    assert capture_contract(source).digest != captured.digest
    assert b' Alice ' in captured.canonical


@pytest.mark.parametrize('change', ['title', 'detail', 'selector', 'expect', 'value', 'key', 'order', 'setup-order'])
def test_semantic_changes_invalidate_identity(change):
    source = requirements()
    original = capture_contract(source)
    if change in ('title', 'detail'): source[0][change] = 'changed'
    elif change in ('selector', 'expect'): source[0]['checks'][1][change] = '#different'
    elif change == 'value': source[0]['checks'][1]['setup'][0]['value'] = 'Alice'
    elif change == 'key': source[0]['checks'][1]['setup'][1]['key'] = 'Tab'
    elif change == 'order': source[0]['checks'].reverse()
    else: source[0]['checks'][1]['setup'].reverse()
    assert capture_contract(source).digest != original.digest


@pytest.mark.parametrize('invalid', ['duplicate', 'unknown', 'empty', 'zero-checks', 'surrogate', 'bad-step', 'too-many', 'wrong-type'])
def test_contract_rejects_lossy_or_ambiguous_inputs(invalid):
    source = requirements()
    if invalid == 'duplicate': source.append(copy.deepcopy(source[0]))
    elif invalid == 'unknown': source[0]['ignored'] = 'must not be dropped'
    elif invalid == 'empty': source = []
    elif invalid == 'zero-checks': source[0]['checks'] = []
    elif invalid == 'surrogate': source[0]['title'] = '\ud800'
    elif invalid == 'bad-step': source[0]['checks'][1]['setup'][0]['action'] = 'execute'
    elif invalid == 'too-many': source[0]['checks'] *= 17
    else: source[0]['checks'][0]['selector'] = 123
    with pytest.raises(ContractError): capture_contract(source)


def test_missing_and_empty_setup_share_explicit_canonical_default():
    a = requirements()
    del a[0]['checks'][1]['setup']
    b = copy.deepcopy(a)
    b[0]['checks'][1]['setup'] = []
    assert capture_contract(a) == capture_contract(b)


@pytest.mark.parametrize('raw', [b'{"format":"a","format":"b","requirements":[]}',
    b'\xff', b'[]', b'{}', b'[' * 2000, b' ' * 1048577],
    ids=['duplicate-key', 'invalid-utf8', 'array-root', 'missing-fields', 'deep-json', 'oversize'])
def test_stored_document_rejects_duplicates_invalid_encoding_and_limits(raw):
    with pytest.raises(ContractError): load_contract(raw)


def test_report_requires_exact_coverage_and_strict_boolean():
    contract = capture_contract(requirements())
    results = [{'key': 'submit', 'checkIndex': 0, 'passed': True, 'note': 'found'},
               {'key': 'submit', 'checkIndex': 1, 'passed': False, 'note': 'not found'}]
    report = capture_report(contract, results)
    assert report.total == 2 and report.passed == 1
    assert capture_report(contract, list(reversed(results))) == report
    assert json.loads(report.canonical)['contractDigest'] == contract.digest
    for invalid in [results[:1], [results[0], results[0]],
                    [results[0], {**results[1], 'passed': 1}],
                    [results[0], {**results[1], 'checkIndex': True}],
                    [results[0], {**results[1], 'key': 'foreign'}]]:
        with pytest.raises(ContractError): capture_report(contract, invalid)


def test_stored_report_requires_canonical_exact_contract_and_unique_keys():
    contract = capture_contract(requirements())
    report = capture_report(contract, [
        {'key': 'submit', 'checkIndex': 0, 'passed': True, 'note': 'found'},
        {'key': 'submit', 'checkIndex': 1, 'passed': True, 'note': 'visible'}])
    assert load_report(contract, report.canonical) == report
    for raw in (report.canonical + b' ',
                report.canonical.replace(b'"passed":true', b'"passed":1', 1),
                report.canonical.replace(contract.digest.encode(), b'f' * 64),
                b'{"format":"atom-verification-report-v1","format":"duplicate"}'):
        with pytest.raises(ContractError):
            load_report(contract, raw)
