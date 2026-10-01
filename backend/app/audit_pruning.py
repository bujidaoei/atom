"""Explicit local maintenance owner; no automatic expiry or tenant mutation API."""
import hashlib
import json
import re
import time

from .audit_archive_store import AuditArchiveStore
from .audit_archiving import validate_registered_payload
from .audit_retention import RetentionRepository, _identifier


class PruneError(RuntimeError):
    pass


class _PruneRepository(RetentionRepository):
    _versions = (11,)


def _canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()


class AuditPruning:
    def __init__(self, database, *, store_id, root, verifier_id, expected_image, expected_policy_digest):
        _identifier(store_id,64)
        _identifier(verifier_id)
        if (not isinstance(expected_image,str) or re.fullmatch(r'sha256:[0-9a-f]{64}',expected_image) is None or
                not isinstance(expected_policy_digest,str) or re.fullmatch(r'[0-9a-f]{64}',expected_policy_digest) is None):
            raise PruneError('invalid_prune_verifier')
        self.repository = _PruneRepository(database)
        self.store = AuditArchiveStore(root)
        self.store_id,self.verifier_id = store_id,verifier_id
        self.image,self.policy = expected_image,expected_policy_digest

    def prune(self, *, command_id, operator_id, archive_id, recovery_id, expected_generation, expected_context):
        for value in (command_id,operator_id,archive_id,recovery_id):
            _identifier(value)
        if (type(expected_generation) is not int or not 1<=expected_generation<2**63 or
                not isinstance(expected_context,str) or re.fullmatch(r'[0-9a-f]{64}',expected_context) is None):
            raise PruneError('invalid_prune_request')
        request=dict(command_id=command_id,operator_id=operator_id,archive_id=archive_id,recovery_id=recovery_id,
            expected_generation=expected_generation,expected_context=expected_context,store_id=self.store_id,
            verifier_id=self.verifier_id,image=self.image,policy_digest=self.policy)
        request_sha=hashlib.sha256(_canonical(request)).hexdigest()

        def replay(db):
            old=db.execute('SELECT * FROM security_audit_prune_receipts WHERE command_id=?',(command_id,)).fetchone()
            if old is not None:
                if old['request_sha256']!=request_sha:
                    raise PruneError('prune_identity_conflict')
                return dict(old)

        def anchors(db):
            archive=db.execute('SELECT * FROM security_audit_archives WHERE archive_id=?',(archive_id,)).fetchone()
            recovery=db.execute('SELECT * FROM security_audit_isolated_recoveries WHERE recovery_id=?',(recovery_id,)).fetchone()
            if (archive is None or archive['archive_store_id']!=self.store_id or recovery is None or
                    recovery['archive_id']!=archive_id or recovery['verifier_id']!=self.verifier_id or
                    recovery['image']!=self.image or recovery['policy_digest']!=self.policy or
                    recovery['protocol']!='audit-recovery-v2' or archive['policy_generation']!=expected_generation or
                    archive['context_sha256']!=expected_context):
                raise PruneError('prune_evidence_mismatch')
            return dict(archive),dict(recovery)

        with self.repository._transaction(read_only=True) as db:
            old=replay(db)
            if old is not None:return old
            archive,recovery=anchors(db)
        # Durable replay above reports a past command, not present archive availability.
        payload=self.store.read(expected_sha256=archive['archive_sha256'])
        decoded=validate_registered_payload(payload,archive)
        envelope=dict(protocol=recovery['protocol'],image=recovery['image'],policy_digest=recovery['policy_digest'],
            attempt_id=recovery['attempt_id'],result=dict(archive_sha256=archive['archive_sha256'],
                manifest=decoded['manifest'],events=decoded['events'],recovery_target='isolated_memory_database',
                deletion_authorized=False))
        if hashlib.sha256(_canonical(envelope)).hexdigest()!=recovery['result_sha256']:
            raise PruneError('prune_recovery_mismatch')
        events=decoded['events']
        identities=tuple(event['event_id'] for event in events)
        placeholders=','.join('?' for _ in identities)
        with self.repository._transaction() as db:
            old=replay(db)
            if old is not None:return old
            if anchors(db)!=(archive,recovery):raise PruneError('prune_evidence_changed')
            current=self.repository._plan_snapshot(db,policy_id=archive['policy_id'],expected_generation=expected_generation,
                after=archive['after_sequence'],upper=archive['upper_sequence'],expected_context=expected_context)
            if current['blocked_count'] or _canonical([item['event'] for item in current['items']])!=_canonical(events):
                raise PruneError('prune_candidates_changed')
            deliveries=db.execute('SELECT count(*),sum(state<>\'delivered\') FROM security_audit_delivery WHERE event_id IN ('+
                placeholders+')',identities).fetchone()
            if deliveries[1] or deliveries[0]>10000:raise PruneError('prune_delivery_unsettled')
            now=int(time.time())
            if not recovery['verified_at']<=now<2**63:raise PruneError('prune_clock_unavailable')
            receipt=dict(command_id=command_id,operator_id=operator_id,request_sha256=request_sha,
                archive_id=archive_id,recovery_id=recovery_id,policy_id=archive['policy_id'],policy_generation=expected_generation,
                context_sha256=expected_context,payload_sha256=archive['payload_sha256'],event_count=len(events),occurred_at=now)
            membership={(event['event_id'],event['sequence']) for event in events}
            membership.add(('',0))
            db.create_function('atom_prune_authorized',3,
                lambda command,event,sequence:int(command==command_id and (event,sequence) in membership))
            try:
                db.execute('INSERT INTO security_audit_prune_receipts ('+','.join(receipt)+') VALUES ('+
                           ','.join('?' for _ in receipt)+')',tuple(receipt.values()))
                db.executemany('INSERT INTO security_audit_archived_events VALUES (?,?,?,?,?,?)',
                    [(e['sequence'],e['event_id'],e['scope_kind'],e['scope_id'],e['event_kind'],command_id) for e in events])
                deleted=db.execute('DELETE FROM security_audit_delivery WHERE event_id IN ('+placeholders+')',identities).rowcount
                removed=db.execute('DELETE FROM security_audit_events WHERE event_id IN ('+placeholders+')',identities).rowcount
                markers=db.execute('SELECT count(*) FROM security_audit_archived_events WHERE command_id=?',(command_id,)).fetchone()[0]
                if deleted!=deliveries[0] or removed!=len(events) or markers!=len(events):
                    raise PruneError('prune_count_mismatch')
            finally:
                membership.clear()
                db.create_function('atom_prune_authorized',3,None)
            return receipt
