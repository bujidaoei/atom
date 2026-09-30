# Component acceptance evidence — 2026-09-30

Scope: standalone snapshot library. No API/runtime call site uses it yet; parent isolation acceptance remains open.

## Implementation and failure history
Initial test collection failed as expected with `ModuleNotFoundError: app.snapshots` before implementation. Implemented strict framing/manifest validation, bounded streaming, unique private staging, Linux no-follow descriptor export, metadata exclusions and deterministic identities. Independent read-only review identified cleanup error normalization and missing CONIN$/CONOUT$ reserved names; both corrected with tests. Added `max_entries` to bound traversal of empty/excluded directory entries as well as manifest prefixes.

## Actual checks
- `backend/.venv/Scripts/python.exe -m pytest backend/tests -q --junitxml=.logs/snapshot-regression.xml`: exit 0; final JUnit records 179 cases including subtests, 0 failures/errors, 5 platform skips, 20.924 seconds. The skipped cases require Linux and were run below. One existing Starlette/httpx deprecation warning remains.
- Linux command below: exit 0; 20 unittest methods, 19 passed, 1 intentional skip (non-Linux fail-closed behavior, tested on Windows), 0.012 seconds. Linux links/FIFO, source symlink replacement, `/dev/full`, round-trip/exclusion, source change and traversal-count cases actually ran.
- Windows and Linux received binary/empty/Unicode files, rejected path/manifest corruption and limits, preserved old completed data on failed promotion and stream errors. Fsync/rename/cleanup failures were injected at their OS boundaries and are explicitly fault-injection tests, not power-loss tests.
- Initial unstaged `git diff --check` passed; subsequent staged check included newly added files and caught three Markdown trailing-space line breaks. Removed those spaces and reran the staged check successfully. No changes to `runtime/pi`, frontend or current runtime; their prior results are not represented as new integration acceptance.

```powershell
docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges --memory 128m --pids-limit 32 --tmpfs /tmp:rw,nosuid,nodev,size=32m --mount type=bind,source=D:/bugu_projects/atom/backend/app/snapshots.py,target=/work/app/snapshots.py,readonly --mount type=bind,source=D:/bugu_projects/atom/backend/tests/test_snapshots.py,target=/work/tests/test_snapshots.py,readonly --env PYTHONPATH=/work --env PYTHONDONTWRITEBYTECODE=1 --workdir /work python@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e python -m unittest discover -s /work/tests -v
```

This test container mounts exactly the two source/test files read-only, uses temporary synthetic data, no credentials, host ports or network. Root inside this test container is not a product sandbox profile or a claim of nonroot isolation. Earlier container-limit experiment is separate evidence.

## Requirement mapping and limits
FR-001/SC-001: deterministic byte-exact round trip. FR-002: actual link/special-file denial and malformed name/prefix tests. FR-003/SC-003: policy and boundary/excess tests, finite traversal count. FR-004/SC-002: integrity/truncation/trailing/write/promotion/cleanup tests with prior data preserved. FR-005: real excluded files omitted and incoming protected names rejected. FR-006: stable reason assertions including cleanup failure. FR-007/SC-004: separate Windows/Linux evidence and explicit integration exclusions.

No multi-file snapshot consistency without caller freezing; no credential-content scanner; no authenticated grant; no global concurrent disk quota or retention; no network wall-clock deadline; no directory fsync/power-loss durability claim; no fenced database revision registration; no crash janitor. `cleanup_failed` means a private `.snapshot-*` orphan needs recovery. Files are policy-immutable to consumers, not protected against a compromised trusted service. Unsupported Windows export fails closed. Executable bits and empty directories are intentionally not retained by v1.

Component acceptance PASS within these boundaries. Enterprise/runtime isolation, live generation, GitHub push and production deployment remain unaccepted.

## Broker export integration continuation (2026-10-01)
Feature 008 reuses this component for quiescent real-container output and adds verify_snapshot without host materialization. Parser/path/hash/EOF policy remains shared with receive_snapshot. MAX_ARCHIVE_BYTES is derived from default content/manifest limits and actual magic/length framing (14 bytes); prior broker seed limit was one byte short and its contract/overflow test were corrected. Final full backend: 342 JUnit cases, zero failures/errors, five Windows platform skips. The actual snapshot component suite also ran inside a restricted Linux container with only the unsupported-platform branch skipped; Linux-specific descriptor/link/source/failure scenarios passed. See specs/008-sandbox-broker/evidence.md for commands, real export/reimport/large-output/fault evidence and remaining registration gates. Component verification is not project revision registration.
