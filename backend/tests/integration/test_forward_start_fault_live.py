"""Opt-in live forward fault drill after source handoff, before successor start.

Requires an exact clean successor checkout and image, a currently idle serving
generation and an explicitly chosen public page. The real transaction creates
its paired backup and restores the exact source after the injected failure.
"""

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import urllib.request


sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "deploy"))
import ip_forward_journal as journal  # noqa: E402
import ip_forward_preflight as preflight  # noqa: E402
import ip_forward_recovery as recovery  # noqa: E402
import ip_forward_transaction as transaction  # noqa: E402
import protected_cutover  # noqa: E402


@unittest.skipUnless(os.environ.get("ATOM_REAL_FORWARD_FAULT") == "1",
                     "explicit live forward fault drill opt-in required")
class ForwardStartFaultLiveTest(unittest.TestCase):
    def test_exact_source_is_restored_after_handoff_start_failure(self):
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
        self.assertIsNone(journal.ForwardJournal(
            config, successor_revision).read(),
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
        with patch.object(transaction.ip_forward_start, "start",
                          side_effect=RuntimeError(
                              "injected_after_exact_source_handoff")):
            with self.assertRaisesRegex(
                    transaction.TransactionError, "^forward_start_failed$"):
                transaction.run(
                    config_file=config_file,
                    publication_file=publication_file,
                    source_revision=source_revision,
                    successor_source=successor_source,
                    successor_revision=successor_revision,
                    successor_image=successor_image)

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
        self.assertEqual(recovery.recover(
            config_file=config_file, publication_file=publication_file,
            successor_revision=successor_revision), "source_restored")


if __name__ == "__main__":
    unittest.main()
