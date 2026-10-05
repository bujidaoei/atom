"""Opt-in real forward fault after the successor is publicly exposed.

The test fails the final console probe after normal ingress answers. Recovery
must restore the source only if the candidate write fence is unchanged.
"""

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import urllib.request


sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "deploy"))
import ip_forward_exposure as exposure  # noqa: E402
import ip_forward_journal as journal  # noqa: E402
import ip_forward_preflight as preflight  # noqa: E402
import ip_forward_recovery as recovery  # noqa: E402
import ip_forward_transaction as transaction  # noqa: E402
import protected_cutover  # noqa: E402


@unittest.skipUnless(os.environ.get("ATOM_REAL_FORWARD_EXPOSURE_FAULT") == "1",
                     "explicit live post-exposure drill opt-in required")
class ForwardExposureFaultLiveTest(unittest.TestCase):
    def test_exposed_successor_recovers_without_discarding_writes(self):
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
        successor_revision = values["ATOM_FAULT_SUCCESSOR_REVISION"]
        public_url = values["ATOM_FAULT_PUBLIC_URL"]
        self.assertTrue(config_file.is_absolute()
                        and publication_file.is_absolute()
                        and successor_source.is_absolute()
                        and public_url.startswith("https://"),
                        "invalid_forward_fault_input")
        config = protected_cutover.load_config(config_file)
        forward_journal = journal.ForwardJournal(config, successor_revision)
        self.assertIsNone(forward_journal.read(), "successor_journal_already_exists")
        before = preflight.inspect_current(
            config_file=config_file, publication_file=publication_file,
            revision=values["ATOM_FAULT_SOURCE_REVISION"],
            successor_source=successor_source,
            successor_revision=successor_revision,
            successor_image=values["ATOM_FAULT_SUCCESSOR_IMAGE"])
        self.assertEqual(before["status"], "ready_for_forward_transaction")

        def public_bytes() -> bytes:
            with urllib.request.urlopen(public_url, timeout=15) as response:
                self.assertEqual(response.status, 200)
                payload = response.read(2 * 1024 * 1024 + 1)
            self.assertTrue(0 < len(payload) <= 2 * 1024 * 1024)
            return payload

        original = public_bytes()
        original_await = exposure.ip_cutover_rollback._await_console
        faulted = False

        def fail_after_normal_ingress(url):
            nonlocal faulted
            original_await(url)
            if not faulted:
                self.assertEqual(forward_journal.read()["phase"],
                                 "exposure_intent")
                faulted = True
                raise RuntimeError("injected_after_real_successor_exposure")

        with patch.object(exposure.ip_cutover_rollback, "_await_console",
                          side_effect=fail_after_normal_ingress):
            with self.assertRaisesRegex(
                    transaction.TransactionError, "^forward_exposure_failed$"):
                transaction.run(
                    config_file=config_file,
                    publication_file=publication_file,
                    source_revision=values["ATOM_FAULT_SOURCE_REVISION"],
                    successor_source=successor_source,
                    successor_revision=successor_revision,
                    successor_image=values["ATOM_FAULT_SUCCESSOR_IMAGE"])

        self.assertTrue(faulted, "normal_ingress_fault_not_reached")
        record = forward_journal.read()
        self.assertIsNotNone(record)
        self.assertIn(record["phase"], {"source_restored", "successor_retained"})
        self.assertTrue(Path(record["capture"]["backupDirectory"]).is_dir())
        retained = record["phase"] == "successor_retained"
        expected_revision = (successor_revision if retained else
                             values["ATOM_FAULT_SOURCE_REVISION"])
        after = preflight.inspect_current(
            config_file=config_file, publication_file=publication_file,
            revision=expected_revision)
        self.assertEqual(after["status"], "current_generation_verified")
        self.assertEqual(after["activeOriginCount"], before["activeOriginCount"])
        if retained:
            self.assertEqual(after["containerIds"],
                             record["candidate"]["containerIds"])
            self.assertNotEqual(after["containerIds"], before["containerIds"])
            self.assertTrue(public_bytes())
        else:
            self.assertEqual(after["containerIds"], before["containerIds"])
            self.assertEqual(public_bytes(), original)
        self.assertEqual(recovery.recover(
            config_file=config_file, publication_file=publication_file,
            successor_revision=successor_revision), record["phase"])


if __name__ == "__main__":
    unittest.main()
