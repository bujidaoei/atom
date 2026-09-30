# Implementation Plan: Verified sandbox snapshots
**Branch**: `codex/006-sandbox-snapshots` | **Date**: 2026-09-30 | **Spec**: [spec.md](spec.md)

## Summary
Build bounded uncompressed snapshot transfer and private verified staging, the first isolation-contract component. Do not replace live copy_tree until broker lifecycle, fenced revision registration and migration are accepted under parent 003.

## Technical Context
Python 3.12+, standard library only, independent of settings/DB. Linux source traversal uses directory descriptors and O_NOFOLLOW; receiving is portable with exclusive trusted parent. pytest/unittest on Windows plus real Linux container tests. Defaults: 4096 files, 16384 traversed entries/inventory prefixes, 8 MiB/file, 64 MiB total, 1 MiB manifest, 1024 UTF-8 path bytes, 32 components. Positive integer policy validation. Bounded I/O chunks, no compression. No SLA claim.

## Constitution Check
Pre/post design PASS: based on reproduced host boundary and quota findings; preserve Pi/user work, no credentials, actual denial tests required. Stream deadlines, process-crash cleanup and power-loss durability remain caller responsibilities, not component guarantees.

## Project Structure
- `backend/app/snapshots.py`: policy, inventory, export and receive.
- `backend/tests/test_snapshots.py`: real filesystem and hostile stream tests.
- `specs/006-sandbox-snapshots/`: specification, design, contract, readiness, tasks and evidence.

## Design
Magic/version, four-byte big-endian manifest length, strict UTF-8 JSON inventory, ordered raw bytes. File SHA-256 plus canonical manifest digest. Reject duplicate/unknown fields, type confusion, normalization/case aliases and file-as-parent collisions. No tar extraction, owner/mode metadata or executable bits. Digests prove consistency, not authorization.

Linux exporter opens root/descendants through no-follow directory descriptors, rejects hardlinks/special files, filters metadata, hashes first pass and verifies bytes/digests on second pass. A frozen source is required; consistency checks do not create an atomic multi-file snapshot. Unsupported platforms fail explicitly.

Receiver uses an unpredictable private staging directory and exclusive creates; verifies all hashes and EOF, fsyncs files, renames to unique completed directory in the same trusted parent. Never replaces a current pointer or caller-selected destination. Normal exception cleanup removes only this staging directory; cleanup I/O failure emits redacted `cleanup_failed` and leaves a private orphan requiring recovery. Caller must independently register/fence revision and manage retention and crash orphans.

## Delivery Strategy
US1 codec/staging → US2 Linux export and adversarial tests → review/evidence. Broker/runtime/cancel/recovery remain open in parent 003.

Broker integration continuation (feature 008): added verify_snapshot for bounded in-memory verification using the shared manifest parser and file digests, plus MAX_ARCHIVE_BYTES for the default format bound. This function creates no artifact or revision. Existing receive_snapshot retains private staging/materialization behavior; broker checkpoints use verification before returning output bytes. Integration scope and evidence remain governed by specs/008-sandbox-broker/contracts/checkpoint-export.md and evidence.md.
