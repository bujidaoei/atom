"""Logical candidate fingerprints distinguish data writes from page layout."""

from contextlib import closing
import importlib.util
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest


DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
sys.path.insert(0, str(DEPLOY))
spec = importlib.util.spec_from_file_location(
    "candidate_write_fence", DEPLOY / "candidate_write_fence.py")
fence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fence)


class CandidateWriteFenceTest(unittest.TestCase):
    def test_layout_changes_do_not_look_like_user_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary).resolve()
            path = data / "atom.db"
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("CREATE TABLE content(id INTEGER PRIMARY KEY, body BLOB)")
                db.execute("INSERT INTO content VALUES (1, ?)", (b"real-content",))
                db.executemany("INSERT INTO content VALUES (?, ?)",
                               [(index, b"padding" * 100) for index in range(2, 200)])
                db.execute("DELETE FROM content WHERE id>1")
            original = fence.database_fingerprint(path)
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("VACUUM")
            self.assertEqual(fence.database_fingerprint(path), original)
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("UPDATE content SET body=? WHERE id=1", (b"changed",))
            self.assertNotEqual(fence.database_fingerprint(path), original)

    def test_state_fingerprint_covers_files_and_schema(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary).resolve()
            with closing(sqlite3.connect(data / "atom.db")) as db, db:
                db.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, note TEXT)")
                db.execute("INSERT INTO items VALUES (1, 'saved')")
            artifact = data / "published" / "index.html"
            artifact.parent.mkdir()
            artifact.write_text("first", encoding="utf-8")
            baseline = fence.state_fingerprint(data)
            artifact.write_text("second", encoding="utf-8")
            self.assertNotEqual(fence.state_fingerprint(data), baseline)
            artifact.write_text("first", encoding="utf-8")
            self.assertEqual(fence.state_fingerprint(data), baseline)
            with closing(sqlite3.connect(data / "atom.db")) as db, db:
                db.execute("CREATE TABLE new_user_state(id INTEGER PRIMARY KEY)")
            self.assertNotEqual(fence.state_fingerprint(data), baseline)

    def test_refuses_symlinked_candidate_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary).resolve()
            with closing(sqlite3.connect(data / "atom.db")) as db, db:
                db.execute("CREATE TABLE content(id INTEGER PRIMARY KEY)")
            target = data / "target.txt"
            target.write_text("value", encoding="utf-8")
            link = data / "linked.txt"
            try:
                link.symlink_to(target)
            except OSError:
                self.skipTest("symlink creation is unavailable")
            with self.assertRaisesRegex(fence.FenceError, "candidate_symlink_present"):
                fence.state_fingerprint(data)


if __name__ == "__main__":
    unittest.main()
