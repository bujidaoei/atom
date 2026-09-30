# Research decisions — 2026-09-30

Decision: bounded manifest plus raw bytes; no tar extraction. Rationale: no link/device/PAX/decompression semantics needed for current file tools. Python explicitly warns that tar filters do not solve resource exhaustion, live mutation or case shadowing: https://docs.python.org/3.12/library/tarfile.html#hints-for-further-verification . Alternative tar data filter rejected as a larger unnecessary boundary.

Decision: strict JSON hook/schema, then canonical identity. Python JSON defaults accept duplicate keys and non-finite numbers; explicitly reject them: https://docs.python.org/3.12/library/json.html . Identity is not authorization.

Decision: descriptor-relative Linux export; private staging and unique rename for receive. https://docs.python.org/3.12/library/os.html documents dir_fd, no-follow operations and rename. Atomic rename is not power-loss durability or database fencing. Existing storage.copy_tree deletes prior destination first and cannot be reused for verified promotion.

Evidence: parent isolation contract and actual local-sandbox/container-limit probes. Independent planning research by snapshot_review agrees on path aliases at every directory prefix, real link tests and frozen sources. Stopping a tmpfs container may lose data: future broker must prove a quiesce-and-export lifecycle, not assume stop-then-copy works. No unresolved component technology choices; broker remains separate work.

Review refinement: normalize cleanup failures and document private orphan recovery. Include CONIN$/CONOUT$ device names, identified in Python's reserved-name guidance: https://docs.python.org/3/library/os.path.html#os.path.isreserved . Actual hostile-name cases were added to the test corpus.
