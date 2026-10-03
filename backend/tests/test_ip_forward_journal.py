"""Durable forward phase order and post-exposure recovery boundary."""

import json
import os
from pathlib import Path
import sys
import tempfile
from unittest import TestCase, main, skipUnless


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "deploy"))
import ip_forward_identity as identity  # noqa: E402
import ip_forward_journal as journal  # noqa: E402
import protected_cutover  # noqa: E402


@skipUnless(os.name == "posix" and getattr(os, "geteuid", lambda: -1)() == 0,
            "root POSIX private-file semantics")
class ForwardJournalTest(TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="atom-forward-journal-")
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        backup, state = root / "backup", root / "state"
        backup.mkdir(mode=0o700)
        state.mkdir(mode=0o700)
        self.revision = "b" * 40
        source_revision = "a" * 40
        self.config = protected_cutover.CutoverConfig(
            "atom-candidate", "atom-candidate-broker", root / "data",
            root / "broker", backup, state, "atom-network", 18080,
            18, 3, Path("/usr/bin/docker"), Path("/var/run/docker.sock"))
        self.receipt = {
            "format": 1, "sourceRevision": source_revision,
            "successorRevision": self.revision,
            "sourceImageId": "sha256:" + "c" * 64,
            "successorImageId": "sha256:" + "d" * 64,
            "sourceDirectory": str(backup / ("candidate-" + source_revision[:12])),
            "backupDirectory": str(backup / ("forward-pre-" + self.revision[:12])),
            "candidateDirectory": str(backup / ("forward-candidate-" +
                                               self.revision[:12])),
            "containerIds": {role: f"{index:064x}" for index, role in
                             enumerate(identity.ROLES, start=1)},
            "heldNames": {role: identity._name(self.config, role) +
                          "-forward-" + source_revision[:7]
                          for role in identity.ROLES},
            "serviceIps": {role: f"172.30.0.{index + 2}" for index, role in
                           enumerate(identity.PINNED_ROLES)},
            "caddy": {"base": identity._bytes_record(b"base"),
                      "active": identity._bytes_record(b"active")},
        }
        path = state / (self.revision + ".forward.json")
        path.write_text(json.dumps(self.receipt), encoding="utf-8")
        path.chmod(0o600)
        self.log = journal.ForwardJournal(self.config, self.revision)

    def _through(self, last: str):
        self.log.begin()
        for phase in journal.PHASES[1:]:
            if phase == "captured":
                self.log.advance(phase, capture={
                    "backupDirectory": self.receipt["backupDirectory"],
                    "candidateDirectory": self.receipt["candidateDirectory"],
                    "manifestSha256": "e" * 64, "caddySha256": "f" * 64,
                    "cosInventorySha256": "a" * 64, "artifactCount": 62,
                    "originCount": 72})
            elif phase == "candidate_ready":
                self.log.advance(phase, candidate={
                    "directory": self.receipt["candidateDirectory"],
                    "imageId": self.receipt["successorImageId"],
                    "containerIds": {role: f"{index + 100:064x}"
                                     for index, role in enumerate(identity.ROLES)},
                    "baselineSha256": "b" * 64,
                    "caddySha256": "c" * 64})
            else:
                self.log.advance(phase)
            if phase == last:
                break

    def test_phase_order_receipt_and_tamper_refusal(self):
        self._through("captured")
        record = self.log.read()
        self.assertEqual(record["phase"], "captured")
        self.assertEqual(record["capture"]["artifactCount"], 62)
        self.assertEqual(self.log.path.stat().st_mode & 0o777, 0o600)
        with self.assertRaisesRegex(journal.JournalError,
                                    "invalid_forward_phase_transition"):
            self.log.advance("exposure_intent")
        self.assertEqual(self.log.read()["phase"], "captured")
        identity_path = self.log.identity_path
        identity_path.write_text(identity_path.read_text() + "\n")
        with self.assertRaisesRegex(journal.JournalError,
                                    "forward_journal_identity_mismatch"):
            self.log.read()

    def test_exposure_requires_write_fence_before_source_restore(self):
        self._through("exposure_intent")
        with self.assertRaisesRegex(journal.JournalError,
                                    "forward_exposure_requires_fence"):
            self.log.advance("source_restored")
        self.assertEqual(self.log.read()["phase"], "exposure_intent")
        self.log.advance("source_restored", evidence={"writeFence": "unchanged"})
        with self.assertRaisesRegex(journal.JournalError,
                                    "invalid_forward_phase_transition"):
            self.log.advance("accepted")

    def test_pre_exposure_recovery_and_terminal_refusal(self):
        self._through("writers_intent")
        self.log.advance("source_restored", evidence={"sourceIdsChecked": True})
        self.assertEqual(self.log.read()["phase"], "source_restored")
        with self.assertRaisesRegex(journal.JournalError, "forward_journal_exists"):
            self.log.begin()

    def test_capture_path_and_file_mode_tampering_refused(self):
        self._through("captured")
        record = self.log.read()
        record["capture"]["backupDirectory"] = "/tmp/other"
        self.log.path.write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaisesRegex(journal.JournalError,
                                    "invalid_forward_capture_receipt"):
            self.log.read()
        self.log.path.chmod(0o644)
        with self.assertRaisesRegex(journal.JournalError,
                                    "insecure_forward_journal"):
            self.log.read()

    def test_candidate_handoff_requires_exact_new_ids_and_baseline(self):
        self._through("candidate_intent")
        bad = {"directory": self.receipt["candidateDirectory"],
               "imageId": self.receipt["successorImageId"],
               "containerIds": dict(self.receipt["containerIds"]),
               "baselineSha256": "b" * 64, "caddySha256": "c" * 64}
        with self.assertRaisesRegex(journal.JournalError,
                                    "invalid_forward_candidate_receipt"):
            self.log.advance("candidate_ready", candidate=bad)
        self.assertEqual(self.log.read()["phase"], "candidate_intent")
        good = dict(bad)
        good["containerIds"] = {role: f"{index + 100:064x}"
                                for index, role in enumerate(identity.ROLES)}
        self.log.advance("candidate_ready", candidate=good)
        self.assertEqual(self.log.read()["candidate"]["baselineSha256"], "b" * 64)


if __name__ == "__main__":
    main()
