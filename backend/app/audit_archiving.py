"""Local trusted-operator archive publication and independently anchored recovery."""
import asyncio
import hashlib
import json
import time

from .audit_archive import ArchiveError, decode_archive, encode_archive, recover_archive
from .audit_archive_store import AuditArchiveStore
from .audit_retention import RetentionRepository, _identifier


def validate_registered_payload(payload, row):
    restored = decode_archive(payload,expected_sha256=row['archive_sha256'])
    fields = ('format_version','coverage','scope_kind','scope_id','event_kind','context_sha256',
              'plan_sha256','payload_sha256','payload_bytes','event_count','upper_sequence')
    if (len(payload) != row['archive_bytes'] or restored['manifest']['after'] != row['after_sequence'] or
            any(restored['manifest'][key] != row[key] for key in fields)):
        raise ArchiveError('archive_recovery_mismatch')
    return restored


class AuditArchiving:
    def __init__(self, database, *, store_id, root):
        _identifier(store_id, 64)
        self.repository = RetentionRepository(database)
        self.store_id = store_id
        self.store = AuditArchiveStore(root)
        with self.repository._transaction(read_only=True) as db:
            self._schema(db)

    @staticmethod
    def _schema(db):
        # The owning repository transaction has already checked exact DDL and migration hashes.
        if db.execute('PRAGMA user_version').fetchone()[0] not in (9, 10):
            raise ArchiveError('archive_schema_required')

    def archive(self, *, archive_id, operator_id, policy_id, expected_generation, after=0, upper=None, expected_context=None):
        for value in (archive_id, operator_id, policy_id): _identifier(value)
        if (type(expected_generation) is not int or not 1 <= expected_generation < 2**63 or
                type(after) is not int or not 0 <= after < 2**63 or
                (upper is not None and (type(upper) is not int or not after <= upper < 2**63))):
            raise ArchiveError('invalid_archive_request')
        with self.repository._transaction(read_only=True) as db:
            self._schema(db)
            old = db.execute('SELECT * FROM security_audit_archives WHERE archive_id=?', (archive_id,)).fetchone()
        if old is not None:
            old = dict(old)
            if (any(old[key] != value for key, value in dict(operator_id=operator_id,policy_id=policy_id,
                    policy_generation=expected_generation,after_sequence=after,archive_store_id=self.store_id).items()) or
                    upper is not None and old['upper_sequence'] != upper or
                    expected_context is not None and old['context_sha256'] != expected_context):
                raise ArchiveError('archive_identity_conflict')
            # Replay proves the object is still readable; never substitutes a new digest or repairs corruption.
            self.store.read(expected_sha256=old['archive_sha256'])
            return old
        plan = self.repository.plan(policy_id=policy_id,expected_generation=expected_generation,
            after=after,upper=upper,expected_context=expected_context)
        policy = plan['context']['policy']
        if policy['archive_store_id'] != self.store_id:
            raise ArchiveError('archive_store_mismatch')
        if not plan['items'] or plan['blocked_count']:
            raise ArchiveError('archive_candidates_required')
        events = [item['event'] for item in plan['items']]
        encoded = encode_archive(events=events,context_sha256=plan['context_sha256'],plan_sha256=plan['plan_sha256'],
            scope_kind=policy['scope_kind'],scope_id=policy['scope_id'],event_kind=policy['event_kind'],
            after=after,upper_sequence=plan['upper_sequence'])
        # No database transaction spans file IO. A failed registration may leave a safe unregistered object.
        self.store.put(encoded.payload, expected_sha256=encoded.sha256)
        recovered = recover_archive(self.store.read(expected_sha256=encoded.sha256), expected_sha256=encoded.sha256)
        metadata = recovered['manifest']
        with self.repository._transaction() as db:
            self._schema(db)
            current = self.repository._plan_snapshot(db,policy_id=policy_id,expected_generation=expected_generation,
                after=after,upper=plan['upper_sequence'],expected_context=plan['context_sha256'])
            if current['blocked_count'] or [item['event'] for item in current['items']] != events:
                raise ArchiveError('archive_source_changed')
            now = int(time.time())
            if not 0 <= now < 2**63: raise ArchiveError('archive_clock_unavailable')
            row = dict(archive_id=archive_id,operator_id=operator_id,policy_id=policy_id,
                policy_generation=expected_generation,archive_store_id=self.store_id,
                format_version=1,coverage=metadata['coverage'],scope_kind=policy['scope_kind'],scope_id=policy['scope_id'],
                event_kind=policy['event_kind'],context_sha256=plan['context_sha256'],plan_sha256=plan['plan_sha256'],
                archive_sha256=encoded.sha256,archive_bytes=len(encoded.payload),payload_sha256=metadata['payload_sha256'],
                payload_bytes=metadata['payload_bytes'],event_count=len(events),after_sequence=after,
                upper_sequence=plan['upper_sequence'],observed_at=plan['observed_at'],registered_at=max(now,plan['observed_at']))
            previous = db.execute('SELECT * FROM security_audit_archives WHERE archive_id=?',(archive_id,)).fetchone()
            if previous is not None:
                if any(previous[key] != value for key,value in row.items() if key != 'registered_at'):
                    raise ArchiveError('archive_identity_conflict')
                return dict(previous)
            db.execute('INSERT INTO security_audit_archives ('+','.join(row)+') VALUES ('+','.join('?' for _ in row)+')', tuple(row.values()))
            return row

    def recover(self, *, archive_id, recovery_id, verifier_id):
        for value in (archive_id,recovery_id,verifier_id): _identifier(value)
        with self.repository._transaction(read_only=True) as db:
            self._schema(db)
            if db.execute('PRAGMA user_version').fetchone()[0] != 9:
                raise ArchiveError('isolated_recovery_required')
            row = db.execute('SELECT * FROM security_audit_archives WHERE archive_id=?',(archive_id,)).fetchone()
            if row is None or row['archive_store_id'] != self.store_id:
                raise ArchiveError('archive_not_found')
            row = dict(row)
        self._read_registered(row)
        with self.repository._transaction() as db:
            self._schema(db)
            previous = db.execute('SELECT * FROM security_audit_archive_recoveries WHERE recovery_id=?',(recovery_id,)).fetchone()
            if previous:
                if previous['archive_id'] != archive_id or previous['verifier_id'] != verifier_id:
                    raise ArchiveError('recovery_identity_conflict')
                return dict(previous)
            now = int(time.time())
            if not 0 <= now < 2**63: raise ArchiveError('archive_clock_unavailable')
            receipt = dict(recovery_id=recovery_id,archive_id=archive_id,verifier_id=verifier_id,
                archive_sha256=row['archive_sha256'],payload_sha256=row['payload_sha256'],event_count=row['event_count'],
                verified_at=max(now,row['registered_at']))
            db.execute('INSERT INTO security_audit_archive_recoveries ('+','.join(receipt)+') VALUES ('+','.join('?' for _ in receipt)+')', tuple(receipt.values()))
            return receipt

    async def recover_isolated(self, *, archive_id, recovery_id, verifier_id, client):
        """Trusted owner: validated remote restore precedes one immutable receipt commit."""
        from .sandbox.audit_recovery_client import AuditRecoveryClient
        if not isinstance(client, AuditRecoveryClient):
            raise ArchiveError('invalid_recovery_client')
        for value in (archive_id, recovery_id, verifier_id):
            _identifier(value)
        image, policy = client.verification_identity
        def previous(db):
            old = db.execute('SELECT * FROM security_audit_isolated_recoveries WHERE recovery_id=?', (recovery_id,)).fetchone()
            if old is not None:
                if any(old[key] != value for key, value in dict(archive_id=archive_id,
                        verifier_id=verifier_id,image=image,policy_digest=policy).items()):
                    raise ArchiveError('recovery_identity_conflict')
                return dict(old)
        def prepare():
            with self.repository._transaction(read_only=True) as db:
                if db.execute('PRAGMA user_version').fetchone()[0] != 10:
                    raise ArchiveError('isolated_recovery_schema_required')
                row = db.execute('SELECT * FROM security_audit_archives WHERE archive_id=?', (archive_id,)).fetchone()
                if row is None or row['archive_store_id'] != self.store_id:
                    raise ArchiveError('archive_not_found')
                old = previous(db)
                row = dict(row)
            return row, self._registered_payload(row), old
        # Cancellation during read/transport cannot schedule a receipt write.
        row, payload, old = await asyncio.to_thread(prepare)
        if old is not None:
            return old
        result = await client.recover(payload, expected_sha256=row['archive_sha256'])
        digest = hashlib.sha256(json.dumps(result,sort_keys=True,separators=(',',':'),ensure_ascii=True,
                                           allow_nan=False).encode()).hexdigest()
        # Short bounded synchronous transaction: no network/file IO and no await after admission.
        # Cancellation cannot detach an unowned background write; callers can inspect/replay by ID.
        with self.repository._transaction() as db:
            if db.execute('PRAGMA user_version').fetchone()[0] != 10:
                raise ArchiveError('isolated_recovery_schema_required')
            current = db.execute('SELECT * FROM security_audit_archives WHERE archive_id=?', (archive_id,)).fetchone()
            if current is None or dict(current) != row:
                raise ArchiveError('archive_source_changed')
            old = previous(db)
            if old is not None:
                return old
            now = int(time.time())
            if not 0 <= now < 2**63:
                raise ArchiveError('archive_clock_unavailable')
            receipt = dict(recovery_id=recovery_id,archive_id=archive_id,verifier_id=verifier_id,
                protocol=result['protocol'],image=result['image'],policy_digest=result['policy_digest'],
                attempt_id=result['attempt_id'],archive_sha256=row['archive_sha256'],payload_sha256=row['payload_sha256'],
                event_count=row['event_count'],result_sha256=digest,verified_at=max(now,row['registered_at']))
            db.execute('INSERT INTO security_audit_isolated_recoveries ('+','.join(receipt)+') VALUES ('+
                       ','.join('?' for _ in receipt)+')', tuple(receipt.values()))
            return receipt

    def _registered_payload(self, row):
        # Expected identity comes exclusively from the immutable ledger, not caller/object metadata.
        payload = self.store.read(expected_sha256=row['archive_sha256'])
        validate_registered_payload(payload,row)
        return payload

    def _read_registered(self, row):
        return recover_archive(self._registered_payload(row),expected_sha256=row['archive_sha256'])

    def inspect(self, *, archive_id):
        """Inspect committed bytes and bounded continuation without issuing a recovery receipt."""
        _identifier(archive_id)
        with self.repository._transaction(read_only=True) as db:
            self._schema(db)
            row = db.execute('SELECT * FROM security_audit_archives WHERE archive_id=?',(archive_id,)).fetchone()
            if row is None or row['archive_store_id'] != self.store_id:
                raise ArchiveError('archive_not_found')
            row = dict(row)
        restored = self._read_registered(row)
        last = restored['events'][-1]['sequence']
        with self.repository._transaction(read_only=True) as db:
            self._schema(db)
            more = db.execute('SELECT EXISTS(SELECT 1 FROM security_audit_events WHERE scope_kind=? AND scope_id=? '
                'AND event_kind=? AND sequence>? AND sequence<=?)',
                (row['scope_kind'],row['scope_id'],row['event_kind'],last,row['upper_sequence'])).fetchone()[0]
            receipts = db.execute('SELECT count(*) FROM security_audit_archive_recoveries WHERE archive_id=?',(archive_id,)).fetchone()[0]
            isolated = (db.execute('SELECT count(*) FROM security_audit_isolated_recoveries WHERE archive_id=?',
                                  (archive_id,)).fetchone()[0]
                        if db.execute('PRAGMA user_version').fetchone()[0] == 10 else None)
        continuation = dict(policy_id=row['policy_id'],expected_generation=row['policy_generation'],after=last,
            upper=row['upper_sequence'],expected_context=row['context_sha256']) if more else None
        result = dict(archive=row,last_sequence=last,continuation=continuation,recovery_receipts=receipts,deletion_authorized=False)
        if isolated is not None:
            result['isolated_recovery_receipts'] = isolated
        return result
