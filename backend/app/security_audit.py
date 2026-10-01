"""Typed audit writes on an already verified, owned business transaction."""
from uuid import uuid4


def record_console_transition(db, *, kind, user_id, source_session_id, occurred_at, affected_count=1):
    if kind not in ('console.session.created', 'console.session.revoked', 'console.account_sessions.revoked'):
        raise ValueError('invalid_console_audit_kind')
    if not db.in_transaction or db.execute('PRAGMA user_version').fetchone()[0] != 5:
        raise ValueError('audit_transaction_required')
    db.execute('''INSERT INTO security_audit_events
        (event_id,schema_version,event_kind,occurred_at,actor_kind,actor_id,scope_kind,scope_id,
         source_session_id,affected_count) VALUES (?,1,?,?,'user',?,'account',?,?,?)''',
        (uuid4().hex,kind,occurred_at,user_id,user_id,source_session_id,affected_count))
