"""Version-one audit event fields and isolated recovery table; standard library only."""
EVENT_FIELDS = ('sequence','event_id','schema_version','event_kind','occurred_at','actor_kind','actor_id',
           'scope_kind','scope_id','operation_id','source_session_id','binding_id','release_id',
           'revision_id','publication_generation','affected_count')

_INTEGER_FIELDS = {"sequence", "schema_version", "occurred_at", "publication_generation", "affected_count"}
RECOVERY_TABLE_SQL = "CREATE TABLE security_audit_events (" + ",".join(
    name + (" INTEGER" if name in _INTEGER_FIELDS else " TEXT") +
    (" PRIMARY KEY" if name == "sequence" else " UNIQUE" if name == "event_id" else "")
    for name in EVENT_FIELDS) + ")"
