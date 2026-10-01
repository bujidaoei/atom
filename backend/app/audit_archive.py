"""Bounded audit archive codec and isolated recovery; no storage or prune authority."""
from dataclasses import dataclass
import hashlib
import json
import re
import sqlite3

from .audit_repository import _FIELDS
from .migrations.audit_v5 import SCHEMA


MAX_ARCHIVE_BYTES = 262144
MAX_EVENTS = 100
_META = {'format_version', 'coverage', 'context_sha256', 'plan_sha256', 'scope_kind',
         'scope_id', 'event_kind', 'after', 'upper_sequence', 'event_count',
         'payload_bytes', 'payload_sha256'}
_KINDS = {
    'account': {'console.session.created', 'console.session.revoked', 'console.account_sessions.revoked'},
    'project': {'content.handoff.issued', 'content.session.created', 'release.published', 'release.unpublished'},
}


class ArchiveError(RuntimeError):
    pass


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii')


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def _sha(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def _integer(value, minimum=0):
    return type(value) is int and minimum <= value < 2**63


def _text(value, maximum=100, pattern=None):
    return (isinstance(value, str) and 1 <= len(value) <= maximum and
            not any(0xD800 <= ord(char) <= 0xDFFF or char == '\0' for char in value) and
            (pattern is None or re.fullmatch(pattern, value) is not None))


def _event(event):
    if type(event) is not dict or set(event) != set(_FIELDS):
        raise ArchiveError('invalid_archive_event')
    if (not _integer(event['sequence'], 1) or type(event['schema_version']) is not int or event['schema_version'] != 1 or
            not _integer(event['occurred_at']) or not _text(event['event_id'], 32, '[0-9a-f]{32}') or
            event['scope_kind'] not in ('account', 'project') or
            not _text(event['scope_id'], pattern='[A-Za-z0-9_.-]+') or
            not isinstance(event['event_kind'], str) or event['event_kind'] not in _KINDS[event['scope_kind']] or
            event['actor_kind'] not in ('user', 'system')):
        raise ArchiveError('invalid_archive_event')
    if ((event['actor_kind'] == 'user' and not _text(event['actor_id'], pattern='[A-Za-z0-9_.-]+')) or
            (event['actor_kind'] == 'system' and event['actor_id'] is not None)):
        raise ArchiveError('invalid_archive_event')
    for key in ('source_session_id', 'binding_id'):
        if event[key] is not None and not _text(event[key], 32, '[0-9a-f]{32}'):
            raise ArchiveError('invalid_archive_event')
    for key in ('operation_id', 'release_id', 'revision_id'):
        if event[key] is not None and not _text(event[key]):
            raise ArchiveError('invalid_archive_event')
    if (event['publication_generation'] is not None and not _integer(event['publication_generation'], 1) or
            event['affected_count'] is not None and (not _integer(event['affected_count'], 1) or event['affected_count'] > 128)):
        raise ArchiveError('invalid_archive_event')


def _validate(metadata, events):
    if type(metadata) is not dict or set(metadata) != _META or type(events) is not list or not 1 <= len(events) <= MAX_EVENTS:
        raise ArchiveError('invalid_archive')
    if (type(metadata['format_version']) is not int or metadata['format_version'] != 1 or
            metadata['coverage'] != 'business_audit_events_v1' or
            not all(_sha(metadata[key]) for key in ('context_sha256', 'plan_sha256', 'payload_sha256')) or
            metadata['scope_kind'] not in ('account', 'project') or
            not _text(metadata['scope_id'], pattern='[A-Za-z0-9_.-]+') or
            not isinstance(metadata['event_kind'], str) or metadata['event_kind'] not in _KINDS[metadata['scope_kind']] or
            not _integer(metadata['after']) or not _integer(metadata['upper_sequence']) or
            not _integer(metadata['event_count'], 1) or metadata['event_count'] != len(events) or
            not _integer(metadata['payload_bytes'], 1)):
        raise ArchiveError('invalid_archive')
    previous, identities = metadata['after'], set()
    for event in events:
        _event(event)
        if (not previous < event['sequence'] <= metadata['upper_sequence'] or event['event_id'] in identities or
                any(event[key] != metadata[key] for key in ('scope_kind', 'scope_id', 'event_kind'))):
            raise ArchiveError('invalid_archive_coverage')
        previous = event['sequence']
        identities.add(event['event_id'])
    payload = _canonical(events)
    if metadata['payload_bytes'] != len(payload) or metadata['payload_sha256'] != _digest(payload):
        raise ArchiveError('archive_payload_mismatch')


@dataclass(frozen=True)
class EncodedArchive:
    payload: bytes
    sha256: str


def encode_archive(*, events, context_sha256, plan_sha256, scope_kind, scope_id, event_kind, after, upper_sequence):
    """Caller supplies captured source evidence; encoding alone grants no authenticity."""
    if type(events) not in (list, tuple) or not 1 <= len(events) <= MAX_EVENTS:
        raise ArchiveError('invalid_archive')
    # Validate before serialization so arbitrary objects/unbounded fields cannot enter the format.
    for event in events:
        _event(event)
    events = list(events)
    payload = _canonical(events)
    metadata = dict(format_version=1, coverage='business_audit_events_v1', context_sha256=context_sha256,
        plan_sha256=plan_sha256, scope_kind=scope_kind, scope_id=scope_id, event_kind=event_kind,
        after=after, upper_sequence=upper_sequence, event_count=len(events), payload_bytes=len(payload), payload_sha256=_digest(payload))
    _validate(metadata, events)
    encoded = _canonical(dict(manifest=metadata, events=events))
    if len(encoded) > MAX_ARCHIVE_BYTES:
        raise ArchiveError('archive_capacity')
    return EncodedArchive(encoded, _digest(encoded))


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ArchiveError('invalid_archive')
        result[key] = value
    return result


def decode_archive(payload, *, expected_sha256):
    """Expected digest must come from trusted external authority, never the object itself."""
    if type(payload) is not bytes or not 1 <= len(payload) <= MAX_ARCHIVE_BYTES:
        raise ArchiveError('archive_capacity')
    if not _sha(expected_sha256) or _digest(payload) != expected_sha256:
        raise ArchiveError('archive_digest_mismatch')
    try:
        value = json.loads(payload, object_pairs_hook=_unique)
        if type(value) is not dict or set(value) != {'manifest', 'events'}:
            raise ArchiveError('invalid_archive')
        _validate(value['manifest'], value['events'])
        if _canonical(value) != payload:
            raise ArchiveError('noncanonical_archive')
        return value
    except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError):
        raise ArchiveError('invalid_archive') from None


def recover_archive(payload, *, expected_sha256):
    """Recreate and compare every typed field in a fresh, isolated SQLite recovery target.

    No source database path/connection is accepted. This result is not a durable recovery receipt.
    """
    archive = decode_archive(payload, expected_sha256=expected_sha256)
    db = sqlite3.connect(':memory:')
    try:
        db.execute(SCHEMA['security_audit_events'])
        db.executemany('INSERT INTO security_audit_events ('+','.join(_FIELDS)+') VALUES ('+','.join('?' for _ in _FIELDS)+')',
                       [tuple(event[key] for key in _FIELDS) for event in archive['events']])
        db.commit()
        db.row_factory = sqlite3.Row
        recovered = [dict(row) for row in db.execute('SELECT '+','.join(_FIELDS)+' FROM security_audit_events ORDER BY sequence')]
        if recovered != archive['events'] or _digest(_canonical(recovered)) != archive['manifest']['payload_sha256']:
            raise ArchiveError('archive_recovery_mismatch')
        return dict(archive_sha256=expected_sha256, manifest=archive['manifest'], events=recovered,
                    recovery_target='isolated_memory_database', deletion_authorized=False)
    except sqlite3.Error:
        raise ArchiveError('archive_recovery_failed') from None
    finally:
        db.close()
