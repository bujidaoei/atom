# Data Model
contract_snapshots: id (32 hex), project_id FK cascade, version positive unique per project, document_json (full bounded validated contract), note, source_id nullable same-project ancestor, created_at. Index(project_id, version DESC). UPDATE forbidden. Head inferred highest version; history remains append-only until project deletion.
contract_approvals: run job identifier, project_id, snapshot_id, created_at; immutable reference proves what was approved.
Snapshot document: requirements with checks, scope[], outOfScope[], architecture string, notes[] (accepted cumulative instructions). Initial legacy baseline preserves existing requirements and latest available planning descriptions without inventing past versions.
State: awaiting_approval/ready/recoverable terminal → planning (refinement) → awaiting_approval on success; failure terminal with old snapshot retained. Restore → awaiting_approval. Approval requires same current version → building. Model output never partially replaces requirements.

