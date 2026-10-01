import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from app.audit_archive import ArchiveError, encode_archive, decode_archive, recover_archive, MAX_ARCHIVE_BYTES
from test_retention_plan import planned, reader, audited_release, release, ledger, legacy


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


@pytest.fixture
def encoded(planned):
    path, repo = planned
    plan = repo.plan(policy_id='policy', expected_generation=1)
    policy = plan['context']['policy']
    artifact = encode_archive(events=[item['event'] for item in plan['items']],
        context_sha256=plan['context_sha256'], plan_sha256=plan['plan_sha256'],
        scope_kind=policy['scope_kind'], scope_id=policy['scope_id'], event_kind=policy['event_kind'],
        after=plan['after'], upper_sequence=plan['upper_sequence'])
    return path, plan, artifact


def test_actual_payloads_recover_in_fresh_process_without_source_database(encoded):
    path, plan, artifact = encoded
    with sqlite3.connect(path) as db:
        original = list(db.iterdump())
    # Only bytes plus expected digest enter the child; no source path or connection is passed.
    script = ('import json,sys; from app.audit_archive import recover_archive; '
              'print(json.dumps(recover_archive(sys.stdin.buffer.read(), expected_sha256=sys.argv[1])))')
    child = subprocess.run([sys.executable, '-c', script, artifact.sha256], input=artifact.payload,
        cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=15)
    assert child.returncode == 0 and not child.stderr
    restored = json.loads(child.stdout)
    assert restored['events'] == [item['event'] for item in plan['items']]
    assert restored['manifest']['context_sha256'] == plan['context_sha256']
    assert restored['manifest']['plan_sha256'] == plan['plan_sha256']
    assert restored['recovery_target'] == 'isolated_memory_database'
    assert not restored['deletion_authorized']
    with sqlite3.connect(path) as db:
        assert list(db.iterdump()) == original


@pytest.mark.parametrize('change', ['truncated', 'corrupt', 'wrong_anchor', 'oversize', 'empty'])
def test_bytes_and_external_anchor_must_match(encoded, change):
    _, _, artifact = encoded
    payload, digest = artifact.payload, artifact.sha256
    if change == 'truncated': payload = payload[:-1]
    if change == 'corrupt': payload = b'!' + payload[1:]
    if change == 'wrong_anchor': digest = '0'*64
    if change == 'oversize': payload = b' '* (MAX_ARCHIVE_BYTES+1)
    if change == 'empty': payload = b''
    with pytest.raises(ArchiveError):
        recover_archive(payload, expected_sha256=digest)


@pytest.mark.parametrize('change', ['duplicate_id', 'reversed', 'extra_event_field', 'missing_field',
    'bool_sequence', 'float_count', 'null_scope', 'list_scope', 'scope_mismatch', 'kind_mismatch',
    'bad_identity', 'unknown_version', 'surrogate', 'null_byte', 'too_long', 'unknown_manifest',
    'bad_count', 'bad_bytes', 'bad_payload_hash', 'bad_upper', 'bool_format', 'bad_context', 'empty_events'])
def test_structural_corruption_rejected_even_with_matching_outer_digest(encoded, change):
    _, _, artifact = encoded
    value = json.loads(artifact.payload)
    event, meta = value['events'][0], value['manifest']
    if change == 'duplicate_id': value['events'][1]['event_id'] = event['event_id']
    elif change == 'reversed': value['events'].reverse()
    elif change == 'extra_event_field': event['credential'] = 'not-a-real-credential'
    elif change == 'missing_field': del event['operation_id']
    elif change == 'bool_sequence': event['sequence'] = True
    elif change == 'float_count': event['affected_count'] = 1.0
    elif change == 'null_scope': event['scope_kind'] = None
    elif change == 'list_scope': event['scope_kind'] = []
    elif change == 'scope_mismatch': event['scope_id'] = 'another-account'
    elif change == 'kind_mismatch': event['event_kind'] = 'release.published'
    elif change == 'bad_identity': event['event_id'] = 'x'*32
    elif change == 'unknown_version': event['schema_version'] = 2
    elif change == 'surrogate': event['operation_id'] = '\ud800'
    elif change == 'null_byte': event['operation_id'] = '\0'
    elif change == 'too_long': event['release_id'] = 'x'*101
    elif change == 'unknown_manifest': meta['verified'] = True
    elif change == 'bad_count': meta['event_count'] += 1
    elif change == 'bad_bytes': meta['payload_bytes'] += 1
    elif change == 'bad_payload_hash': meta['payload_sha256'] = '0'*64
    elif change == 'bad_upper': meta['upper_sequence'] = 0
    elif change == 'bool_format': meta['format_version'] = True
    elif change == 'bad_context': meta['context_sha256'] = 'bad'
    elif change == 'empty_events': value['events'] = []
    if change not in ('bad_bytes', 'bad_payload_hash'):
        event_bytes = canonical(value['events'])
        meta['payload_bytes'] = len(event_bytes)
        meta['payload_sha256'] = hashlib.sha256(event_bytes).hexdigest()
    payload = canonical(value)
    with pytest.raises(ArchiveError):
        decode_archive(payload, expected_sha256=hashlib.sha256(payload).hexdigest())


@pytest.mark.parametrize('change', ['duplicate_key', 'whitespace', 'invalid_json', 'nested', 'nan'])
def test_noncanonical_or_ambiguous_json_rejected(encoded, change):
    _, _, artifact = encoded
    if change == 'duplicate_key': payload = artifact.payload.replace(b'"format_version":1', b'"format_version":1,"format_version":1')
    elif change == 'whitespace': payload = b' '+artifact.payload
    elif change == 'invalid_json': payload = b'not-json'
    elif change == 'nested': payload = b'['*2000+b']'*2000
    else: payload = artifact.payload.replace(b'"format_version":1', b'"format_version":NaN')
    with pytest.raises(ArchiveError):
        decode_archive(payload, expected_sha256=hashlib.sha256(payload).hexdigest())


def test_encoding_bounds_and_unicode_preserve_exact_fields(encoded):
    _, _, artifact = encoded
    value = json.loads(artifact.payload)
    meta = value['manifest']
    options = {key: meta[key] for key in ('context_sha256','plan_sha256','scope_kind','scope_id','event_kind','after','upper_sequence')}
    events = copy.deepcopy(value['events'])
    events[0]['operation_id'] = '恢复验证'
    result = encode_archive(events=events, **options)
    assert recover_archive(result.payload, expected_sha256=result.sha256)['events'] == events
    for invalid in ([], events*34):
        with pytest.raises(ArchiveError):
            encode_archive(events=invalid, **options)
    oversized = []
    for index in range(100):
        event = dict(events[0], sequence=index+1, event_id=f'{index:032x}',
                     operation_id='\U0001f600'*100, release_id='\U0001f600'*100, revision_id='\U0001f600'*100)
        oversized.append(event)
    # Every field is valid; the whole envelope still must meet the byte ceiling.
    with pytest.raises(ArchiveError, match='archive_capacity'):
        encode_archive(events=oversized, **dict(options, upper_sequence=100))


@pytest.mark.parametrize('kind', ['console.session.created','console.session.revoked','console.account_sessions.revoked',
    'content.handoff.issued','content.session.created','release.published','release.unpublished'])
def test_format_supports_all_declared_event_classes(encoded, kind):
    # Codec shape coverage, not evidence that all seven business transitions ran in this test.
    _, _, artifact = encoded
    value = json.loads(artifact.payload)
    meta = value['manifest']
    event = dict(value['events'][0], event_kind=kind,
        scope_kind='account' if kind.startswith('console.') else 'project', actor_kind='system', actor_id=None,
        binding_id='a'*32, release_id='release', revision_id='revision', publication_generation=2)
    result = encode_archive(events=[event], context_sha256=meta['context_sha256'], plan_sha256=meta['plan_sha256'],
        scope_kind=event['scope_kind'], scope_id=event['scope_id'], event_kind=kind, after=0, upper_sequence=event['sequence'])
    assert recover_archive(result.payload, expected_sha256=result.sha256)['events'] == [event]
