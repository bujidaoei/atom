"""Opt-in real forward crash after the first successor container starts.

The child exits without running the transaction's exception handler. A
separate process must reconcile its durable journal and preserve the source.
"""

import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
import urllib.request


sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "deploy"))
import ip_forward_journal as journal  # noqa: E402
import ip_forward_preflight as preflight  # noqa: E402
import ip_forward_recovery as recovery  # noqa: E402
import ip_forward_start as start  # noqa: E402
import ip_forward_transaction as transaction  # noqa: E402
import protected_cutover  # noqa: E402


CRASH_EXIT = 47


def _crash_after_verifier(values: dict[str, str]) -> None:
    """Run the real transaction, then die without Python cleanup."""
    original_compose = start._compose

    def crash(*args, **kwargs):
        original_compose(*args, **kwargs)
        if args[3] == "compose.ip-verifier.yml":
            config = protected_cutover.load_config(Path(values["ATOM_FAULT_CONFIG"]))
            verifier = start._current(config, "verifier")
            if verifier is None or verifier["State"]["Running"] is not True:
                raise AssertionError("successor_verifier_not_running")
            os._exit(CRASH_EXIT)

    with patch.object(start, "_compose", side_effect=crash):
        transaction.run(
            config_file=Path(values["ATOM_FAULT_CONFIG"]),
            publication_file=Path(values["ATOM_FAULT_PUBLICATION_FILE"]),
            source_revision=values["ATOM_FAULT_SOURCE_REVISION"],
            successor_source=Path(values["ATOM_FAULT_SUCCESSOR_SOURCE"]),
            successor_revision=values["ATOM_FAULT_SUCCESSOR_REVISION"],
            successor_image=values["ATOM_FAULT_SUCCESSOR_IMAGE"],
        )


@unittest.skipUnless(os.name == "posix" and
                     os.environ.get("ATOM_REAL_FORWARD_PROCESS_CRASH") == "1",
                     "explicit POSIX forward crash drill opt-in required")
class ForwardProcessCrashLiveTest(unittest.TestCase):
    def test_durable_recovery_after_abrupt_first_successor_exit(self):
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
        worker = multiprocessing.get_context("fork").Process(
            target=_crash_after_verifier, args=(values,))
        worker.start()
        worker.join(timeout=240)
        if worker.is_alive():
            worker.kill()
            worker.join(timeout=15)

        # Recovery is attempted even when the crash did not reach the expected
        # point. Never leave a production maintenance route because an assertion
        # about the injected fault failed.
        candidate_id = None
        try:
            record = forward_journal.read()
            if record is not None and record["phase"] == "candidate_intent":
                item = start._current(config, "verifier")
                if item is not None:
                    candidate_id = item["Id"]
            self.assertEqual(worker.exitcode, CRASH_EXIT)
            self.assertIsNotNone(record)
            self.assertEqual(record["phase"], "candidate_intent")
            self.assertIsNotNone(candidate_id)
            self.assertNotEqual(candidate_id, before["containerIds"]["verifier"])
        finally:
            if forward_journal.read() is not None:
                recovery.recover(
                    config_file=config_file, publication_file=publication_file,
                    successor_revision=successor_revision)

        record = forward_journal.read()
        self.assertEqual(record["phase"], "source_restored")
        self.assertTrue(Path(record["capture"]["backupDirectory"]).is_dir())
        after = preflight.inspect_current(
            config_file=config_file, publication_file=publication_file,
            revision=values["ATOM_FAULT_SOURCE_REVISION"])
        self.assertEqual(after["status"], "current_generation_verified")
        self.assertEqual(after["containerIds"], before["containerIds"])
        self.assertEqual(after["activeOriginCount"], before["activeOriginCount"])
        self.assertEqual(public_bytes(), original)
        self.assertNotEqual(subprocess.run(
            [str(config.docker), "container", "inspect", candidate_id],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            check=False, timeout=10).returncode, 0)
        self.assertEqual(recovery.recover(
            config_file=config_file, publication_file=publication_file,
            successor_revision=successor_revision), "source_restored")


if __name__ == "__main__":
    unittest.main()
