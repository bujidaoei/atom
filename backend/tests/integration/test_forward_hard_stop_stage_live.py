"""Opt-in live handoff point for a Lighthouse HARD-stop recovery drill.

Run this test in the foreground on the target. Its ``POWER_STAGE_READY`` line
is the external operator's signal to hard-stop the instance. If no hard stop
arrives before the bounded deadline, the ordinary transaction exception path
restores the source generation while the same host lock remains held.
"""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
import urllib.request


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "deploy"))
import ip_forward_journal as journal  # noqa: E402
import ip_forward_exposure as exposure  # noqa: E402
import ip_forward_preflight as preflight  # noqa: E402
import ip_forward_start as start  # noqa: E402
import ip_forward_transaction as transaction  # noqa: E402
import protected_cutover  # noqa: E402


STAGED_ROLES = ("verifier", "preview", "public")
STAGE_TIMEOUT_SECONDS = 180


@unittest.skipUnless(os.name == "posix" and
                     os.environ.get("ATOM_REAL_FORWARD_HARD_STOP_STAGE") == "1",
                     "explicit POSIX hard-stop staging opt-in required")
class ForwardHardStopStageLiveTest(unittest.TestCase):
    def test_hold_exact_candidate_intent_until_cloud_hard_stop(self):
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
        successor_image = values["ATOM_FAULT_SUCCESSOR_IMAGE"]
        public_url = values["ATOM_FAULT_PUBLIC_URL"]
        self.assertTrue(config_file.is_absolute()
                        and publication_file.is_absolute()
                        and successor_source.is_absolute()
                        and public_url.startswith("https://"),
                        "invalid_forward_fault_input")
        self.assertEqual(subprocess.run(
            ["systemctl", "is-enabled", "--quiet", "atom-origin-reconcile.timer"],
            check=False, timeout=10).returncode, 0,
            "origin_timer_not_enabled_at_boot")
        self.assertEqual(subprocess.run(
            ["systemctl", "is-active", "--quiet", "atom-origin-reconcile.timer"],
            check=False, timeout=10).returncode, 0,
            "origin_timer_not_active")
        config = protected_cutover.load_config(config_file)
        forward_journal = journal.ForwardJournal(config, successor_revision)
        self.assertIsNone(forward_journal.read(), "successor_journal_already_exists")
        before = preflight.inspect_current(
            config_file=config_file, publication_file=publication_file,
            revision=values["ATOM_FAULT_SOURCE_REVISION"],
            successor_source=successor_source,
            successor_revision=successor_revision,
            successor_image=successor_image)
        self.assertEqual(before["status"], "ready_for_forward_transaction")

        with urllib.request.urlopen(public_url, timeout=15) as response:
            self.assertEqual(response.status, 200)
            public_bytes = response.read(2 * 1024 * 1024 + 1)
        self.assertTrue(0 < len(public_bytes) <= 2 * 1024 * 1024)
        public_sha256 = hashlib.sha256(public_bytes).hexdigest()
        original_compose = start._compose

        def hold_after_content_start(*args, **kwargs):
            original_compose(*args, **kwargs)
            if args[3] != "compose.ip-publication.yml":
                return
            record = forward_journal.read()
            self.assertIsNotNone(record)
            self.assertEqual(record["phase"], "candidate_intent")
            backup = Path(record["capture"]["backupDirectory"])
            manifest = backup / "manifest.json"
            self.assertTrue(manifest.is_file(), "quiesced_backup_missing")
            self.assertTrue(0 < manifest.stat().st_size <= 4 * 1024 * 1024,
                            "quiesced_backup_manifest_unbounded")
            staged_ids = {}
            for role in STAGED_ROLES:
                item = start._current(config, role)
                self.assertIsNotNone(item, "staged_role_missing:" + role)
                self.assertIs(item["State"]["Running"], True)
                staged_ids[role] = item["Id"]
                self.assertNotEqual(item["Id"], before["containerIds"][role])
            print("POWER_STAGE_READY " + json.dumps({
                "sourceRevision": values["ATOM_FAULT_SOURCE_REVISION"],
                "successorRevision": successor_revision,
                "phase": record["phase"],
                "sourceContainerIds": before["containerIds"],
                "stagedContainerIds": staged_ids,
                "originCount": before["activeOriginCount"],
                "publicSha256": public_sha256,
                "backupManifestSha256": hashlib.sha256(
                    manifest.read_bytes()).hexdigest(),
            }, sort_keys=True), flush=True)
            time.sleep(STAGE_TIMEOUT_SECONDS)
            raise RuntimeError("cloud_hard_stop_not_received")

        def refuse_promotion(**_kwargs):
            raise RuntimeError("hard_stop_stage_not_reached")

        with patch.object(start, "_compose", side_effect=hold_after_content_start), \
                patch.object(exposure, "expose", side_effect=refuse_promotion):
            transaction.run(
                config_file=config_file, publication_file=publication_file,
                source_revision=values["ATOM_FAULT_SOURCE_REVISION"],
                successor_source=successor_source,
                successor_revision=successor_revision,
                successor_image=successor_image)
        self.fail("cloud_hard_stop_not_received")
