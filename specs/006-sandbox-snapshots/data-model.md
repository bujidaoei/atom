# Snapshot entities
Limits: positive integers for file count/bytes, total bytes, manifest bytes, path bytes and depth.
Entry: canonical NFC relative POSIX `path`, nonnegative integer `size`, lowercase 64-hex `sha256`.
Manifest: version 1, sorted entries. No links, modes, host paths or timestamps. Revision: SHA-256 of canonical compact UTF-8 JSON with sorted keys.
ReceivedSnapshot: revision, immutable tuple of entries, generated completed directory path.
States: private staging → verified completed; normal failure → cleaned. Process death may leave private orphans; no automatic accepted revision.
