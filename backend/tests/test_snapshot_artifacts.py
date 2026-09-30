import hashlib
import json
import os
from pathlib import Path
import stat
import struct
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from app.artifacts import ArtifactError, ArtifactStore


def archive(data=b"content", padding=False):
    manifest = json.dumps({"version": 1, "files": [{"path": "a", "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}]},
                          indent=2 if padding else None).encode()
    return b"ATOMSNAP1\n" + struct.pack(">I", len(manifest)) + manifest + data


@unittest.skipUnless(sys.platform == "linux", "durable directory fsync and no-follow storage require Linux")
class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "artifacts"
        self.root.mkdir(mode=0o700)
        self.store = ArtifactStore(self.root)

    def test_exact_bytes_dedup_and_semantic_revision(self):
        first = self.store.put(archive())
        self.assertEqual(self.store.put(archive()), first)
        self.assertEqual(self.store.read(first.key), archive())
        another = self.store.put(archive(padding=True))
        self.assertNotEqual(first.key, another.key)
        self.assertEqual(first.revision, another.revision)
        self.assertEqual(len(list(self.root.iterdir())), 2)

    def test_real_concurrent_publication_has_one_immutable_object(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: ArtifactStore(self.root).put(archive()), range(16)))
        self.assertTrue(all(item == results[0] for item in results))
        self.assertEqual(len(list(self.root.iterdir())), 1)

    def test_bad_payload_or_corrupt_existing_object_never_overwrites(self):
        with self.assertRaises(ArtifactError):
            self.store.put(archive()[:-1])
        self.assertEqual(list(self.root.iterdir()), [])
        stored = self.store.put(archive())
        target = self.root / (stored.key + ".atomsnap")
        target.write_bytes(b"corrupt")
        for action in [lambda: self.store.read(stored.key), lambda: self.store.put(archive())]:
            with self.assertRaises(ArtifactError):
                action()
        self.assertEqual(target.read_bytes(), b"corrupt")

    def test_nonprivate_roots_and_unsafe_objects_fail_closed(self):
        self.root.chmod(0o755)
        with self.assertRaises(ArtifactError):
            ArtifactStore(self.root)
        self.root.chmod(0o700)
        alias = self.root.parent / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ArtifactError):
            ArtifactStore(alias)
        stored = self.store.put(archive())
        target = self.root / (stored.key + ".atomsnap")
        outside = self.root.parent / "outside"
        os.link(target, outside)
        with self.assertRaises(ArtifactError):
            self.store.read(stored.key)
        outside.unlink()
        target.unlink()
        outside.write_bytes(b"canary")
        target.symlink_to(outside)
        with self.assertRaises(ArtifactError):
            self.store.read(stored.key)
        self.assertEqual(outside.read_bytes(), b"canary")

    def test_failed_publication_preserves_prior_and_cleans_stage(self):
        prior = self.store.put(archive())
        with patch("app.artifacts.os.link", side_effect=OSError("synthetic failure")):
            with self.assertRaises(ArtifactError):
                self.store.put(archive(b"new"))
        self.assertEqual(self.store.read(prior.key), archive())
        self.assertEqual(len(list(self.root.iterdir())), 1)

    def test_process_death_before_publication_recovers_stage(self):
        prior = self.store.put(archive())
        pid = os.fork()
        if pid == 0:
            with patch("app.artifacts.os.link", side_effect=lambda *a, **k: os._exit(43)):
                self.store.put(archive(b"new"))
            os._exit(99)
        _, status = os.waitpid(pid, 0)
        self.assertEqual(os.waitstatus_to_exitcode(status), 43)
        self.assertTrue(any(path.name.startswith(".stage-") for path in self.root.iterdir()))
        recovered = ArtifactStore(self.root)
        self.assertEqual(recovered.read(prior.key), archive())
        self.assertEqual(len(list(self.root.iterdir())), 1)
        recovered.put(archive(b"new"))
        self.assertEqual(len(list(self.root.iterdir())), 2)

    def test_recovery_never_unlinks_unsafe_stage_or_unrecognized_file(self):
        outside = self.root.parent / "outside"
        outside.write_bytes(b"canary")
        link = self.root / (".stage-" + "a" * 32)
        link.symlink_to(outside)
        with self.assertRaises(ArtifactError):
            ArtifactStore(self.root)
        self.assertTrue(link.is_symlink())
        self.assertEqual(outside.read_bytes(), b"canary")
        link.unlink()
        unknown = self.root / "operator-note"
        unknown.write_bytes(b"keep")
        ArtifactStore(self.root)
        self.assertEqual(unknown.read_bytes(), b"keep")

    def test_process_death_after_link_preserves_published_object(self):
        payload = archive(b"published")
        original = os.link
        pid = os.fork()
        if pid == 0:
            def interrupted(*args, **kwargs):
                original(*args, **kwargs)
                os._exit(47)
            with patch("app.artifacts.os.link", side_effect=interrupted):
                self.store.put(payload)
            os._exit(99)
        _, status = os.waitpid(pid, 0)
        self.assertEqual(os.waitstatus_to_exitcode(status), 47)
        self.assertEqual(len(list(self.root.iterdir())), 2)
        recovered = ArtifactStore(self.root)
        key = hashlib.sha256(payload).hexdigest()
        self.assertEqual(recovered.read(key), payload)
        self.assertEqual(len(list(self.root.iterdir())), 1)

    def test_capacity_reserves_recovery_slot(self):
        limited = ArtifactStore(self.root, scan_limit=2)
        first = limited.put(archive())
        with self.assertRaisesRegex(ArtifactError, "artifact_capacity"):
            limited.put(archive(b"new"))
        self.assertEqual(limited.put(archive()), first)
        self.assertEqual(ArtifactStore(self.root, scan_limit=2).read(first.key), archive())

    def test_directory_sync_failure_is_not_acknowledged_but_retry_confirms(self):
        original = os.fsync
        def failed_directory_sync(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError("synthetic directory sync failure")
            return original(fd)
        payload = archive(b"published")
        with patch("app.artifacts.os.fsync", side_effect=failed_directory_sync):
            with self.assertRaises(ArtifactError):
                self.store.put(payload)
        stored = ArtifactStore(self.root).put(payload)
        self.assertEqual(self.store.read(stored.key), payload)

    def test_real_process_lock_has_finite_wait(self):
        import fcntl
        ready_read, ready_write = os.pipe()
        release_read, release_write = os.pipe()
        pid = os.fork()
        if pid == 0:
            descriptor = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            os.write(ready_write, b"1")
            os.read(release_read, 1)
            os._exit(0)
        try:
            self.assertEqual(os.read(ready_read, 1), b"1")
            started = time.monotonic()
            with self.assertRaisesRegex(ArtifactError, "artifact_store_busy"):
                ArtifactStore(self.root, lock_timeout=0.05)
            self.assertLess(time.monotonic() - started, 1)
        finally:
            os.write(release_write, b"1")
            _, status = os.waitpid(pid, 0)
            for descriptor in (ready_read, ready_write, release_read, release_write):
                os.close(descriptor)
        self.assertEqual(os.waitstatus_to_exitcode(status), 0)


if __name__ == "__main__":
    unittest.main()
