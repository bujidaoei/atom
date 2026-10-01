"""Actual Linux filesystem/fork probes; event fixtures test storage, not business transitions."""
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

from app.audit_archive import encode_archive, recover_archive, ArchiveError
from app.audit_archive_store import AuditArchiveStore


@unittest.skipUnless(sys.platform == 'linux', 'requires actual Linux filesystem semantics')
class ArchiveStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)/'archives'
        self.root.mkdir(mode=0o700)
        self.store = AuditArchiveStore(self.root)
        event = dict(sequence=1,event_id='a'*32,schema_version=1,event_kind='console.session.created',
            occurred_at=100,actor_kind='user',actor_id='user',scope_kind='account',scope_id='user',
            operation_id=None,source_session_id='b'*32,binding_id=None,release_id=None,revision_id=None,
            publication_generation=None,affected_count=1)
        self.archive = encode_archive(events=[event],context_sha256='c'*64,plan_sha256='d'*64,
            scope_kind='account',scope_id='user',event_kind='console.session.created',after=0,upper_sequence=1)
        self.path = self.root/(self.archive.sha256+'.atomaudit')

    def put(self):
        return self.store.put(self.archive.payload, expected_sha256=self.archive.sha256)

    def test_durable_idempotent_reopen_and_recover(self):
        receipt = self.put()
        self.assertEqual(self.put(), receipt)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o400)
        self.assertEqual(self.path.stat().st_nlink, 1)
        payload = AuditArchiveStore(self.root).read(expected_sha256=receipt.sha256)
        restored = recover_archive(payload, expected_sha256=receipt.sha256)
        self.assertEqual(restored['events'][0]['event_id'], 'a'*32)
        self.assertFalse(restored['deletion_authorized'])

    def test_corruption_never_overwritten(self):
        self.put()
        self.path.chmod(0o600)
        self.path.write_bytes(b'corrupt')
        with self.assertRaises(ArchiveError): self.put()
        with self.assertRaises(ArchiveError): self.store.read(expected_sha256=self.archive.sha256)
        self.assertEqual(self.path.read_bytes(), b'corrupt')

    def test_links_fifo_permissions_and_unknown_entries(self):
        external = self.root.parent/'external'
        external.write_bytes(self.archive.payload)
        external.chmod(0o600)
        self.path.symlink_to(external)
        with self.assertRaises(ArchiveError): self.put()
        self.path.unlink()
        os.link(external, self.path)
        with self.assertRaises(ArchiveError): self.put()
        self.path.unlink()
        os.mkfifo(self.path, 0o600)
        with self.assertRaises(ArchiveError): self.put()
        self.path.unlink()
        self.put()
        self.path.chmod(0o644)
        with self.assertRaises(ArchiveError): self.store.read(expected_sha256=self.archive.sha256)
        self.path.unlink()
        (self.root/'unknown').write_text('unowned')
        with self.assertRaises(ArchiveError): AuditArchiveStore(self.root)

    def test_unsafe_roots_and_bad_configuration(self):
        self.root.chmod(0o755)
        with self.assertRaises(ArchiveError): AuditArchiveStore(self.root)
        self.root.chmod(0o700)
        link = self.root.parent/'link'
        link.symlink_to(self.root)
        with self.assertRaises(ArchiveError): AuditArchiveStore(link)
        for timeout in (True, float('nan'), 0, 11):
            with self.assertRaises(ArchiveError): AuditArchiveStore(self.root, lock_timeout=timeout)

    def test_partial_write_failure_cleans_unpublished_stage(self):
        original = os.write
        calls = []
        def write(descriptor, view):
            if calls: raise OSError('injected write failure')
            calls.append(True)
            return original(descriptor, view[:20])
        with patch('app.audit_archive_store.os.write', write):
            with self.assertRaises(ArchiveError): self.put()
        self.assertEqual(list(self.root.iterdir()), [])
        self.put()

    def test_actual_process_death_before_and_after_publish(self):
        original = os.link
        for when in ('before', 'after'):
            with self.subTest(when=when):
                pid = os.fork()
                if pid == 0:
                    def link(*args, **kwargs):
                        if when == 'after': original(*args, **kwargs)
                        os._exit(71)
                    with patch('app.audit_archive_store.os.link', link): self.put()
                    os._exit(72)
                _, status = os.waitpid(pid, 0)
                self.assertEqual(os.waitstatus_to_exitcode(status), 71)
                self.assertTrue(any(p.name.startswith('.stage-') for p in self.root.iterdir()))
                reopened = AuditArchiveStore(self.root)
                self.assertFalse(any(p.name.startswith('.stage-') for p in self.root.iterdir()))
                self.assertEqual(self.path.exists(), when == 'after')
                reopened.put(self.archive.payload, expected_sha256=self.archive.sha256)
                self.assertEqual(reopened.read(expected_sha256=self.archive.sha256), self.archive.payload)
                self.path.unlink()

    def test_lock_deadline_and_capacity(self):
        import fcntl
        descriptor = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            with self.assertRaisesRegex(ArchiveError, 'archive_store_busy'):
                AuditArchiveStore(self.root, lock_timeout=.03)
        finally:
            os.close(descriptor)
        self.put()
        # Reserve space for a transient staging entry; never silently remove published objects.
        store = AuditArchiveStore(self.root, max_entries=2)
        other = self.root/('0'*64+'.atomaudit')
        self.path.rename(other)
        with self.assertRaisesRegex(ArchiveError, 'archive_store_capacity'):
            store.put(self.archive.payload, expected_sha256=self.archive.sha256)

    def test_sync_failure_never_acknowledged(self):
        original = os.fsync
        for directory_failure in (False, True):
            with self.subTest(directory_failure=directory_failure):
                def sync(descriptor):
                    is_directory = stat.S_ISDIR(os.fstat(descriptor).st_mode)
                    if is_directory == directory_failure: raise OSError('injected sync failure')
                    original(descriptor)
                with patch('app.audit_archive_store.os.fsync', sync):
                    with self.assertRaises(ArchiveError): self.put()
                # A failure after link may leave an object; retry must verify/sync it before acknowledgement.
                self.assertEqual(self.path.exists(), directory_failure)
                self.put()
                self.assertEqual(self.store.read(expected_sha256=self.archive.sha256), self.archive.payload)
                self.path.unlink()

    def test_two_actual_writers_publish_one_object(self):
        children = []
        for _ in range(2):
            pid = os.fork()
            if pid == 0:
                try:
                    self.put()
                    os._exit(0)
                except Exception:
                    os._exit(73)
            children.append(pid)
        for pid in children:
            self.assertEqual(os.waitstatus_to_exitcode(os.waitpid(pid, 0)[1]), 0)
        self.assertEqual(list(self.root.iterdir()), [self.path])
        self.assertEqual(self.path.stat().st_nlink, 1)


if __name__ == '__main__':
    unittest.main()
