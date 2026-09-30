# Broker-local registry v1

T003 is a durable local ownership component, not distributed control-plane authority. Caller must supply a cryptographically verified Grant and trusted administrative identity for revocation/termination. Registry independently rechecks time, fingerprint, latest run fence, revoked status and permitted state. No secret/token storage or Docker calls.

SQLite in a service-private existing directory, WAL, synchronous FULL, finite lock timeout. Schema version 1 created only in an empty database; unknown versions or mismatching schema fail closed without deletion/migration. A persisted random broker identity determines ownership labels. Each operation uses its own connection and short BEGIN IMMEDIATE transaction; no external side effect under database lock.

Admission: unique grant ID and unique organization/project/run/attempt. Same grant fingerprint returns same attempt/container name; changed fingerprint conflicts. Latest head per organization/project/run stores fence/attempt. A higher fence may replace only an attempt whose termination is confirmed; lower/equal fresh fence fails. Revocation tombstones work before admission and persist across restart. Expiry never permits replacement while termination remains unknown.

States: intent→provisioning→ready→quiescing→checkpointed. Scoped transition checks expected version and legal edge. Checkpointed requires validated revision digest. Administrative termination intent may interrupt any nonterminal state and increments version, fencing stale completion. Only terminating/termination_unknown can record verified termination; confirmed→terminated, unconfirmed→termination_unknown. Cleanup remains possible after grant expiry/revocation, but only via trusted administrative methods. These methods record driver evidence supplied by the future lifecycle layer; they do not themselves prove a container died.

Revocation records a tombstone and sets existing nonterminal attempt to terminating, blocking operations immediately. Deadline sweep marks expired nonterminal attempts terminating; separate driver reconciliation must confirm termination. Bounded paginated unterminated listing supports recovery; startup readiness/reconciliation belongs to T006.

Errors are stable codes without SQL, host paths or grant content. SQLite contention/unavailability never becomes empty success. This component promises restart persistence/transactional serialization as tested, not host-loss durability or HA. History/tombstone retention must not permit still-valid replay; no automatic deletion in v1.
