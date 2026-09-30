# Snapshot stream v1
Magic `ATOMSNAP1\n`, unsigned 32-bit big-endian manifest length, strict UTF-8 JSON `{ "version": 1, "files": [{"path": "index.html", "size": 0, "sha256": "..."}] }`, then exactly the files' bytes in path order; strict EOF. Empty directories are not represented. JSON whitespace need not be canonical; revision uses canonical serialization.

Reject empty/dot/dotdot segments, absolute paths, backslashes, colons, controls, Windows special characters/devices, trailing space/dot, non-NFC forms, casefold aliases (including directory prefixes), file-parent conflicts. Export omits any case-insensitive `.env*`, `.git`, `.pi`, `node_modules`, `__pycache__` component; receiver rejects them. Export rejects symlinks, hardlinks and special files. No executable modes retained.

`export_snapshot(root, stream, limits=Limits()) -> str`; `receive_snapshot(stream, parent, limits=Limits()) -> ReceivedSnapshot`. `SnapshotError.code` contains a stable reason only. Caller supplies frozen source, private trusted parent, authenticated stream/deadlines, quota/retention and revision registration. No HTTP endpoint exists in this increment.
