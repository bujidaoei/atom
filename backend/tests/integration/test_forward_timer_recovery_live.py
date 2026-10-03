"""Opt-in real crash recovered by the installed host origin timer.

The timer, not this test process, must move candidate_intent to a terminal
receipt. A manual fallback in finally protects the serving site if it fails.
"""

import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
import urllib.request


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "deploy"))
import ip_forward_journal as journal  # noqa: E402
import ip_forward_preflight as preflight  # noqa: E402
import ip_forward_recovery as recovery  # noqa: E402
import protected_cutover  # noqa: E402
from backend.tests.integration.test_forward_later_partial_crash_live import (  # noqa: E402
    CRASH_EXIT, STARTED_ROLES, _crash_after_content_services,
)


@unittest.skipUnless(os.name == "posix" and
                     os.environ.get("ATOM_REAL_FORWARD_TIMER_RECOVERY") == "1",
                     "explicit POSIX timer recovery drill opt-in required")
class ForwardTimerRecoveryLiveTest(unittest.TestCase):
    def test_timer_recovers_three_role_crash_without_manual_action(self):
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
        self.assertEqual(subprocess.run(
            ["systemctl", "is-active", "--quiet", "atom-origin-reconcile.timer"],
            check=False, timeout=10).returncode, 0, "origin_timer_not_active")
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
            target=_crash_after_content_services, args=(values,))
        worker.start()
        worker.join(timeout=240)
        if worker.is_alive():
            worker.kill()
            worker.join(timeout=15)

        try:
            self.assertEqual(worker.exitcode, CRASH_EXIT)
            record = forward_journal.read()
            self.assertIsNotNone(record)
            self.assertIn("candidate_intent",
                          [event["phase"] for event in record["events"]])
            # No direct recovery call from this process until the deadline.
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                record = forward_journal.read()
                if record["phase"] == "source_restored":
                    break
                if record["phase"] in {"successor_retained", "accepted"}:
                    self.fail("timer_selected_unexpected_generation")
                time.sleep(2)
            self.assertEqual(record["phase"], "source_restored",
                             "timer_did_not_recover_interrupted_forward")
        finally:
            record = forward_journal.read()
            if record is not None and record["phase"] not in {
                    "source_restored", "successor_retained", "accepted"}:
                for _attempt in range(15):
                    try:
                        recovery.recover(
                            config_file=config_file,
                            publication_file=publication_file,
                            successor_revision=successor_revision)
                        break
                    except protected_cutover.CutoverError as exc:
                        if str(exc) != "cutover_lock_busy":
                            raise
                        time.sleep(2)
                else:
                    raise AssertionError("manual_recovery_lock_unavailable")

        record = forward_journal.read()
        self.assertTrue(Path(record["capture"]["backupDirectory"]).is_dir())
        self.assertEqual(record["phase"], "source_restored")
        after = preflight.inspect_current(
            config_file=config_file, publication_file=publication_file,
            revision=values["ATOM_FAULT_SOURCE_REVISION"])
        self.assertEqual(after["status"], "current_generation_verified")
        self.assertEqual(after["containerIds"], before["containerIds"])
        self.assertEqual(after["activeOriginCount"], before["activeOriginCount"])
        self.assertEqual(public_bytes(), original)
        for role in STARTED_ROLES:
            held = before["containerIds"][role]
            self.assertEqual(after["containerIds"][role], held)
        self.assertEqual(subprocess.run(
            ["systemctl", "is-active", "--quiet", "atom-origin-reconcile.timer"],
            check=False, timeout=10).returncode, 0)


if __name__ == "__main__":
    unittest.main()
