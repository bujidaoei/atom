"""Opt-in real forward fault after the first successor container starts.

The protected transaction must stop and remove that exact candidate, then
restore the original serving generation without discarding a publication.
"""

import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request


sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "deploy"))
import ip_forward_journal as journal  # noqa: E402
import ip_forward_preflight as preflight  # noqa: E402
import ip_forward_recovery as recovery  # noqa: E402
import ip_forward_start as start  # noqa: E402
import ip_forward_transaction as transaction  # noqa: E402
import protected_cutover  # noqa: E402


@unittest.skipUnless(os.environ.get("ATOM_REAL_FORWARD_PARTIAL_START_FAULT") == "1",
                     "explicit live partial-start drill opt-in required")
class ForwardPartialStartFaultLiveTest(unittest.TestCase):
    def test_exact_source_and_publication_survive_first_successor_start(self):
        keys = (
            "ATOM_FAULT_CONFIG", "ATOM_FAULT_PUBLICATION_FILE",
            "ATOM_FAULT_SOURCE_REVISION", "ATOM_FAULT_SUCCESSOR_SOURCE",
            "ATOM_FAULT_SUCCESSOR_REVISION", "ATOM_FAULT_SUCCESSOR_IMAGE",
            "ATOM_FAULT_PUBLIC_URL",
        )
        values = {key: os.environ.get(key, "") for key in keys}
        self.assertTrue(all(values.values()), "missing_forward_fault_input")
        config_file = Path(values["ATOM_FAULT_CONFIG"])
        publication_file = Path(values["ATOM_FAULT_PUBLICATION_FILE"])
        successor_source = Path(values["ATOM_FAULT_SUCCESSOR_SOURCE"])
        source_revision = values["ATOM_FAULT_SOURCE_REVISION"]
        successor_revision = values["ATOM_FAULT_SUCCESSOR_REVISION"]
        successor_image = values["ATOM_FAULT_SUCCESSOR_IMAGE"]
        public_url = values["ATOM_FAULT_PUBLIC_URL"]
        self.assertTrue(config_file.is_absolute()
                        and publication_file.is_absolute()
                        and successor_source.is_absolute()
                        and public_url.startswith("https://"),
                        "invalid_forward_fault_input")

        config = protected_cutover.load_config(config_file)
        self.assertIsNone(journal.ForwardJournal(config, successor_revision).read(),
                          "successor_journal_already_exists")
        before = preflight.inspect_current(
            config_file=config_file, publication_file=publication_file,
            revision=source_revision, successor_source=successor_source,
            successor_revision=successor_revision,
            successor_image=successor_image)
        self.assertEqual(before["status"], "ready_for_forward_transaction")

        def public_bytes() -> bytes:
            with urllib.request.urlopen(public_url, timeout=15) as response:
                self.assertEqual(response.status, 200)
                payload = response.read(2 * 1024 * 1024 + 1)
            self.assertTrue(0 < len(payload) <= 2 * 1024 * 1024)
            return payload

        original = public_bytes()
        candidate_ids = []
        compose = start._compose

        def fail_after_verifier(*args, **kwargs):
            compose(*args, **kwargs)
            if args[3] == "compose.ip-verifier.yml":
                item = start._current(config, "verifier")
                self.assertIsNotNone(item)
                self.assertTrue(item["State"]["Running"])
                self.assertNotEqual(item["Id"], before["containerIds"]["verifier"])
                candidate_ids.append(item["Id"])
                raise RuntimeError("injected_after_real_verifier_start")

        with patch.object(start, "_compose", side_effect=fail_after_verifier):
            with self.assertRaisesRegex(
                    transaction.TransactionError, "^forward_start_failed$"):
                transaction.run(
                    config_file=config_file,
                    publication_file=publication_file,
                    source_revision=source_revision,
                    successor_source=successor_source,
                    successor_revision=successor_revision,
                    successor_image=successor_image)

        self.assertEqual(len(candidate_ids), 1)
        record = journal.ForwardJournal(config, successor_revision).read()
        self.assertIsNotNone(record)
        self.assertEqual(record["phase"], "source_restored")
        self.assertIsNotNone(record["capture"])
        self.assertTrue(Path(record["capture"]["backupDirectory"]).is_dir())
        after = preflight.inspect_current(
            config_file=config_file, publication_file=publication_file,
            revision=source_revision)
        self.assertEqual(after["status"], "current_generation_verified")
        self.assertEqual(after["containerIds"], before["containerIds"])
        self.assertEqual(after["activeOriginCount"], before["activeOriginCount"])
        self.assertEqual(public_bytes(), original)
        self.assertNotEqual(subprocess.run(
            [str(config.docker), "container", "inspect", candidate_ids[0]],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            check=False, timeout=10).returncode, 0)
        self.assertEqual(recovery.recover(
            config_file=config_file, publication_file=publication_file,
            successor_revision=successor_revision), "source_restored")


if __name__ == "__main__":
    unittest.main()
