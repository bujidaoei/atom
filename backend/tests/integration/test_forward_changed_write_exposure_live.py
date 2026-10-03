"""Opt-in real post-exposure fault after an authenticated Atom release write.

The successor must stay serving when its real publication ledger has changed.
This is a production-only selected drill, never part of routine regression.
"""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
import urllib.request


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "deploy"))
import ip_forward_exposure as exposure  # noqa: E402
import ip_forward_journal as journal  # noqa: E402
import ip_forward_preflight as preflight  # noqa: E402
import ip_forward_recovery as recovery  # noqa: E402
import ip_forward_start as start  # noqa: E402
import ip_forward_transaction as transaction  # noqa: E402
import paired_backup  # noqa: E402
import protected_cutover  # noqa: E402


@unittest.skipUnless(os.name == "posix" and
                     os.environ.get("ATOM_REAL_FORWARD_CHANGED_WRITE_EXPOSURE") == "1",
                     "explicit POSIX changed-write exposure opt-in required")
class ForwardChangedWriteExposureLiveTest(unittest.TestCase):
    def test_real_release_write_retains_exposed_successor(self):
        keys = (
            "ATOM_FAULT_CONFIG", "ATOM_FAULT_PUBLICATION_FILE",
            "ATOM_FAULT_SOURCE_REVISION", "ATOM_FAULT_SUCCESSOR_SOURCE",
            "ATOM_FAULT_SUCCESSOR_REVISION", "ATOM_FAULT_SUCCESSOR_IMAGE",
            "ATOM_FAULT_PUBLIC_URL", "ATOM_FAULT_PROJECT_ID",
        )
        values = {key: os.environ.get(key, "") for key in keys}
        self.assertTrue(all(values.values()), "missing_forward_fault_input")
        project_id = values["ATOM_FAULT_PROJECT_ID"]
        self.assertRegex(project_id, r"^[0-9a-f]{32}$")
        config_file = Path(values["ATOM_FAULT_CONFIG"])
        publication_file = Path(values["ATOM_FAULT_PUBLICATION_FILE"])
        source = Path(values["ATOM_FAULT_SUCCESSOR_SOURCE"])
        successor_revision = values["ATOM_FAULT_SUCCESSOR_REVISION"]
        public_url = values["ATOM_FAULT_PUBLIC_URL"]
        self.assertTrue(config_file.is_absolute() and publication_file.is_absolute()
                        and source.is_absolute() and public_url.startswith("https://"),
                        "invalid_forward_fault_input")
        config = protected_cutover.load_config(config_file)
        receipt = journal.ForwardJournal(config, successor_revision)
        self.assertIsNone(receipt.read(), "successor_journal_already_exists")
        before = preflight.inspect_current(
            config_file=config_file, publication_file=publication_file,
            revision=values["ATOM_FAULT_SOURCE_REVISION"], successor_source=source,
            successor_revision=successor_revision,
            successor_image=values["ATOM_FAULT_SUCCESSOR_IMAGE"])
        self.assertEqual(before["status"], "ready_for_forward_transaction")

        def public_hash():
            with urllib.request.urlopen(public_url, timeout=15) as response:
                self.assertEqual(response.status, 200)
                body = response.read(2 * 1024 * 1024 + 1)
            self.assertTrue(0 < len(body) <= 2 * 1024 * 1024)
            return hashlib.sha256(body).hexdigest()

        original_hash = public_hash()
        original_await = exposure.ip_cutover_rollback._await_console
        published = None

        def write_then_fail(url):
            nonlocal published
            original_await(url)
            if published is not None:
                return
            self.assertEqual(receipt.read()["phase"], "exposure_intent")
            candidate_api = start._current(config, "api")
            self.assertIsNotNone(candidate_api)
            self.assertTrue(candidate_api["State"]["Running"])
            self.assertNotEqual(candidate_api["Id"], before["containerIds"]["api"])
            script = (ROOT / "backend/tests/integration/live_forward_release_write.py").read_text("utf-8")
            result = subprocess.run([
                str(config.docker), "exec", "-i",
                "-e", "ATOM_LIVE_FORWARD_RELEASE_WRITE=1",
                "-e", f"ATOM_LIVE_FORWARD_PROJECT_ID={project_id}",
                candidate_api["Id"], "/app/backend/.venv/bin/python", "-",
            ], input=script, text=True, capture_output=True, timeout=90, check=False)
            self.assertEqual(result.returncode, 0, "real_release_write_failed")
            published = json.loads(result.stdout)
            self.assertRegex(published["releaseId"], r"^[0-9a-f]{32}$")
            raise RuntimeError("injected_after_real_release_write")

        with patch.object(exposure.ip_cutover_rollback, "_await_console",
                          side_effect=write_then_fail):
            with self.assertRaisesRegex(
                    transaction.TransactionError, "^forward_exposure_failed$"):
                transaction.run(
                    config_file=config_file, publication_file=publication_file,
                    source_revision=values["ATOM_FAULT_SOURCE_REVISION"],
                    successor_source=source, successor_revision=successor_revision,
                    successor_image=values["ATOM_FAULT_SUCCESSOR_IMAGE"])

        self.assertIsNotNone(published, "real_release_write_not_reached")
        record = receipt.read()
        self.assertEqual(record["phase"], "successor_retained")
        self.assertEqual(record["events"][-1]["evidence"]["writeFence"], "changed")
        self.assertEqual(paired_backup.verify(
            Path(record["capture"]["backupDirectory"]))["status"], "verified")
        after = preflight.inspect_current(
            config_file=config_file, publication_file=publication_file,
            revision=successor_revision)
        self.assertEqual(after["status"], "current_generation_verified")
        self.assertEqual(after["containerIds"], record["candidate"]["containerIds"])
        self.assertNotEqual(after["containerIds"], before["containerIds"])
        self.assertEqual(after["activeOriginCount"], before["activeOriginCount"])
        self.assertNotEqual(public_hash(), original_hash)
        self.assertEqual(recovery.recover(
            config_file=config_file, publication_file=publication_file,
            successor_revision=successor_revision), "successor_retained")


if __name__ == "__main__":
    unittest.main()
