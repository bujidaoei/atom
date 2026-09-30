from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

from app.snapshots import Limits, SnapshotError, export_snapshot, receive_snapshot, verify_snapshot


def entry(path: str, data: bytes = b"x") -> dict:
    return {"path": path, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def wire(files: list, data: bytes = b"", *, raw: bytes | None = None) -> bytes:
    manifest = raw if raw is not None else json.dumps({"version": 1, "files": files}).encode()
    return b"ATOMSNAP1\n" + struct.pack(">I", len(manifest)) + manifest + data


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.parent = self.root / "snapshots"
        self.parent.mkdir()
        self.canary = self.root / "canary"
        self.canary.write_bytes(b"unchanged")

    def reject(self, payload: bytes, code: str | None = None, **kwargs):
        before = set(self.parent.iterdir())
        with self.assertRaises(SnapshotError) as caught:
            receive_snapshot(io.BytesIO(payload), self.parent, **kwargs)
        if code:
            self.assertEqual(caught.exception.code, code)
        self.assertEqual(set(self.parent.iterdir()), before)
        self.assertEqual(self.canary.read_bytes(), b"unchanged")
        if code != "io_error":  # Filesystem failure is specific to materialization.
            with self.assertRaises(SnapshotError):
                verify_snapshot(io.BytesIO(payload), **kwargs)

    def test_verify_without_host_artifacts_matches_receive(self):
        payload = wire([entry("a", b""), entry("nested/中文.bin", b"\x00\xff")], b"\x00\xff")
        received = receive_snapshot(io.BytesIO(payload), self.parent)
        with patch("app.snapshots.tempfile.mkdtemp", side_effect=AssertionError("verification must not stage files")):
            verified = verify_snapshot(io.BytesIO(payload))
        self.assertEqual(verified.revision, received.revision)
        self.assertEqual(verified.files, received.files)

    def test_receive_binary_empty_and_identity(self):
        files = [entry("a", b""), entry("nested/中文.bin", b"\x00\xff")]
        first = receive_snapshot(io.BytesIO(wire(files, b"\x00\xff")), self.parent)
        second = receive_snapshot(io.BytesIO(wire(files, b"\x00\xff")), self.parent)
        self.assertEqual(first.revision, second.revision)
        self.assertNotEqual(first.path, second.path)
        self.assertEqual((first.path / "a").read_bytes(), b"")
        self.assertEqual((first.path / "nested/中文.bin").read_bytes(), b"\x00\xff")
        self.assertEqual(len(first.files), 2)

    def test_empty_snapshot(self):
        result = receive_snapshot(io.BytesIO(wire([])), self.parent)
        self.assertEqual(list(result.path.iterdir()), [])

    def test_bad_paths(self):
        for path in ["../canary", "/canary", "a//b", "a/./b", "a/../b", "C:x", "a\\b",
                     "a\x00b", "a\nb", "a\u202eb", "a.", "a ", "CON", "aux.txt", "COM1.js",
                     "LPT9", "CONIN$", "conout$.txt", "a?b", "a*b", "a|b", "e\u0301", "", "//host/x", "a/<x>"]:
            with self.subTest(path=repr(path)):
                self.reject(wire([entry(path)], b"x"), "invalid_path")

    def test_excluded_paths(self):
        for path in [".env", "a/.ENV.local", ".git/config", ".pi/session", "node_modules/x", "__pycache__/x"]:
            with self.subTest(path=path):
                self.reject(wire([entry(path)], b"x"), "excluded_path")

    def test_collisions_and_sorting(self):
        for paths in [["A/x", "a/y"], ["a", "a/b"], ["a", "a"], ["b", "a"], ["A", "a/b"]]:
            with self.subTest(paths=paths):
                self.reject(wire([entry(path) for path in paths], b"x" * len(paths)))

    def test_strict_manifest(self):
        for raw in [b'{"version":1,"version":1,"files":[]}', b'{"version":true,"files":[]}',
                    b'{"version":1,"files":[],"extra":0}', b'[]', b'null', b'\xff',
                    b'{"version":1,"files":NaN}', b'[' * 1100]:
            with self.subTest(raw=raw[:50]):
                self.reject(wire([], raw=raw), "invalid_manifest")
        for field, value in [("size", True), ("size", -1), ("size", 1.0), ("sha256", "X" * 64),
                             ("path", 42), ("extra", "anything")]:
            item = entry("a")
            item[field] = value
            with self.subTest(field=field, value=value):
                self.reject(wire([item], b"x"))

    def test_truncation_digest_trailing_and_magic(self):
        payload = wire([entry("a", b"abc")], b"abc")
        for cut in [0, 1, 9, 11, len(payload) - 1]:
            self.reject(payload[:cut])
        self.reject(payload[:-1] + b"X", "digest_mismatch")
        self.reject(payload + b"x", "trailing_data")
        self.reject(b"B" + payload[1:], "invalid_magic")

    def test_limits(self):
        good = wire([entry("a", b"xx")], b"xx")
        result = receive_snapshot(io.BytesIO(good), self.parent,
                                  Limits(max_files=1, max_file_bytes=2, max_total_bytes=2, max_path_bytes=1, max_depth=1))
        self.assertEqual((result.path / "a").read_bytes(), b"xx")
        for limits in [Limits(max_file_bytes=1), Limits(max_total_bytes=1), Limits(max_manifest_bytes=1)]:
            self.reject(good, "limit_exceeded", limits=limits)
        self.reject(wire([entry("a"), entry("b")], b"xx"), "limit_exceeded", limits=Limits(max_files=1))
        self.reject(wire([entry("ab")], b"x"), "limit_exceeded", limits=Limits(max_path_bytes=1))
        self.reject(wire([entry("a/b")], b"x"), "limit_exceeded", limits=Limits(max_depth=1))
        self.reject(b"ATOMSNAP1\n" + struct.pack(">I", 2**32 - 1), "limit_exceeded")

    def test_invalid_policy(self):
        for value in [0, -1, True, 1.5, "2"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                Limits(max_files=value)

    def test_manifest_and_entry_limit_boundaries(self):
        items = [entry("a/b")]
        raw = json.dumps({"version": 1, "files": items}, sort_keys=True, separators=(",", ":")).encode()
        result = receive_snapshot(io.BytesIO(wire(items, b"x", raw=raw)), self.parent,
                                  Limits(max_manifest_bytes=len(raw), max_entries=2))
        self.assertEqual((result.path / "a/b").read_bytes(), b"x")
        self.reject(wire(items, b"x", raw=raw), "limit_exceeded", limits=Limits(max_manifest_bytes=len(raw) - 1))
        self.reject(wire(items, b"x"), "limit_exceeded", limits=Limits(max_entries=1))

    def test_failed_promotion_preserves_old_snapshot(self):
        previous = receive_snapshot(io.BytesIO(wire([entry("old")], b"x")), self.parent)
        with patch("app.snapshots.Path.rename", side_effect=OSError("synthetic rename failure")):
            self.reject(wire([entry("new")], b"x"), "io_error")
        self.assertEqual(list(self.parent.iterdir()), [previous.path])

    @unittest.skipUnless(sys.platform == "linux", "real Linux target symlink and write failure")
    def test_linux_target_symlink_and_dev_full(self):
        alias = self.root / "alias"
        alias.symlink_to(self.parent, target_is_directory=True)
        with self.assertRaises(SnapshotError) as caught:
            receive_snapshot(io.BytesIO(wire([])), alias)
        self.assertEqual(caught.exception.code, "invalid_parent")
        source = self.root / "source"
        source.mkdir()
        (source / "a").write_bytes(b"x")
        with open("/dev/full", "wb", buffering=0) as output:
            with self.assertRaises(SnapshotError) as caught:
                export_snapshot(source, output)
        self.assertEqual(caught.exception.code, "io_error")
        self.assertEqual(list(self.parent.iterdir()), [])

    @unittest.skipUnless(sys.platform == "linux", "real Linux source replacement")
    def test_linux_source_replaced_with_outside_symlink(self):
        source = self.root / "source"
        source.mkdir()
        target = source / "a"
        target.write_bytes(b"public")

        class Replace(io.BytesIO):
            def write(inner, data):
                if not target.is_symlink():
                    target.unlink()
                    target.symlink_to(self.canary)
                return super().write(data)

        output = Replace()
        with self.assertRaises(SnapshotError):
            export_snapshot(source, output)
        self.assertNotIn(b"unchanged", output.getvalue())
        self.assertEqual(self.canary.read_bytes(), b"unchanged")

    def test_stream_failure_cleans_and_preserves_previous(self):
        previous = receive_snapshot(io.BytesIO(wire([entry("a")], b"x")), self.parent)

        class Broken(io.BytesIO):
            def read(self, size=-1):
                if self.tell() >= 13:
                    raise OSError("synthetic private content must not leak")
                return super().read(size)

        with self.assertRaises(SnapshotError) as caught:
            receive_snapshot(Broken(wire([entry("a")], b"x")), self.parent)
        self.assertEqual(str(caught.exception), "io_error")
        self.assertEqual(list(self.parent.iterdir()), [previous.path])
        with patch("app.snapshots.os.fsync", side_effect=OSError("disk full")):
            self.reject(wire([entry("a")], b"x"), "io_error")
        self.assertEqual((previous.path / "a").read_bytes(), b"x")

    def test_short_reads(self):
        class Short(io.BytesIO):
            def read(self, size=-1):
                return super().read(min(size, 2))
        result = receive_snapshot(Short(wire([entry("a", b"abc")], b"abc")), self.parent)
        self.assertEqual((result.path / "a").read_bytes(), b"abc")

    def test_cleanup_failure_is_redacted(self):
        with patch("app.snapshots.shutil.rmtree", side_effect=OSError("private host path")):
            with self.assertRaises(SnapshotError) as caught:
                receive_snapshot(io.BytesIO(wire([entry("a")], b"y")), self.parent)
        self.assertEqual(str(caught.exception), "cleanup_failed")
        # An operator/janitor must recover this orphan; it is never completed work.
        self.assertEqual(len(list(self.parent.iterdir())), 1)
        self.assertTrue(next(self.parent.iterdir()).name.startswith(".snapshot-"))

    @unittest.skipUnless(sys.platform == "linux", "secure exporter requires Linux descriptor APIs")
    def test_linux_round_trip_exclusions_and_short_writes(self):
        source = self.root / "source"
        source.mkdir()
        (source / "nested").mkdir()
        (source / "nested/中文.bin").write_bytes(b"\x00\xff")
        (source / "empty").write_bytes(b"")
        (source / ".env.local").write_text("synthetic excluded value")
        (source / ".git").mkdir()
        (source / ".git/config").write_text("synthetic excluded metadata")

        class Short(io.BytesIO):
            def write(self, data):
                return super().write(data[:2])
        stream = Short()
        revision = export_snapshot(source, stream)
        another = io.BytesIO()
        self.assertEqual(export_snapshot(source, another), revision)
        self.assertEqual(stream.getvalue(), another.getvalue())
        result = receive_snapshot(io.BytesIO(stream.getvalue()), self.parent)
        self.assertEqual(result.revision, revision)
        self.assertEqual({item.path for item in result.files}, {"empty", "nested/中文.bin"})

    @unittest.skipUnless(sys.platform == "linux", "real Linux links and FIFO")
    def test_linux_reject_links_and_special_files(self):
        source = self.root / "source"
        source.mkdir()
        target = source / "unsafe"
        for create in [lambda: target.symlink_to(self.canary), lambda: os.link(self.canary, target),
                       lambda: os.mkfifo(target), lambda: target.symlink_to(self.root, target_is_directory=True)]:
            create()
            try:
                with self.assertRaises(SnapshotError):
                    export_snapshot(source, io.BytesIO())
            finally:
                target.unlink()
        self.assertEqual(self.canary.read_bytes(), b"unchanged")

    @unittest.skipUnless(sys.platform == "linux", "real Linux source consistency")
    def test_linux_source_changes_and_entry_limit(self):
        source = self.root / "source"
        source.mkdir()
        file = source / "a"
        file.write_bytes(b"abc")

        class Mutating(io.BytesIO):
            def write(self, data):
                file.write_bytes(b"xyz")
                return super().write(data)
        with self.assertRaises(SnapshotError) as caught:
            export_snapshot(source, Mutating())
        self.assertEqual(caught.exception.code, "source_changed")
        (source / "b").mkdir()
        with self.assertRaises(SnapshotError) as caught:
            export_snapshot(source, io.BytesIO(), Limits(max_entries=1))
        self.assertEqual(caught.exception.code, "limit_exceeded")

    @unittest.skipIf(sys.platform == "linux", "Linux supports secure export")
    def test_unsupported_export_fails_closed(self):
        with self.assertRaises(SnapshotError) as caught:
            export_snapshot(self.root, io.BytesIO())
        self.assertEqual(caught.exception.code, "unsupported_platform")


if __name__ == "__main__":
    unittest.main()
