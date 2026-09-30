# Verification
Run `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_snapshots.py -q`. Run the same unittest tests in the pinned Linux Python 3.12 container with only module/test files mounted read-only. Record commands, image and results in evidence.md. All test data are temporary and synthetic.

Cover text/binary/empty files, deterministic identities, limits, path aliases/traversal, invalid manifests, corruption/truncation/trailing bytes, symlink/hardlink/FIFO, stream failures and source replacement. Preserve previous completed snapshots and outside canaries.
Component PASS does not imply broker/runtime integration, crash recovery, authenticated network transport, live models or production deployment.
