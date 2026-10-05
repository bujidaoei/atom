"""Selected selection and refusal checks for timer-driven forward recovery."""

from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest import TestCase, main
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "deploy"))
import ip_forward_auto_recover as auto  # noqa: E402


class AutoRecoveryTest(TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.config = SimpleNamespace(state_dir=self.directory)
        self.publication = self.directory / "publication.env"
        private_directory = patch.object(auto.ip_forward_journal,
                                         "_private_directory")
        private_directory.start()
        self.addCleanup(private_directory.stop)

    def _receipt(self, revision: str) -> None:
        (self.directory / (revision + auto.SUFFIX)).write_text("sealed")
        (self.directory / (revision + auto.IDENTITY_SUFFIX)).write_text("sealed")

    def test_healthy_awaiting_acceptance_is_not_recovered(self):
        revision = "a" * 40
        self._receipt(revision)
        with patch.object(auto.ip_forward_journal, "ForwardJournal") as journal, \
             patch.object(auto.ip_forward_identity, "read"), \
             patch.object(auto.ip_forward_recovery, "recover_locked") as recovery:
            journal.return_value.read.return_value = {
                "phase": "awaiting_acceptance"}
            result = auto.recover_locked(config=self.config,
                                         publication_file=self.publication)
        self.assertEqual(result, {"status": "no_recovery_needed"})
        recovery.assert_not_called()

    def test_one_interrupted_successor_recovers_under_same_dispatch(self):
        serving, failed = "b" * 40, "c" * 40
        self._receipt(serving)
        self._receipt(failed)
        with patch.object(auto.ip_forward_journal, "ForwardJournal") as journal, \
             patch.object(auto.ip_forward_identity, "read"), \
             patch.object(auto.ip_forward_recovery, "recover_locked",
                          return_value="source_restored") as recovery:
            journal.side_effect = lambda _config, revision: SimpleNamespace(
                read=lambda: {"phase": "awaiting_acceptance" if revision == serving
                              else "candidate_intent"})
            result = auto.recover_locked(config=self.config,
                                         publication_file=self.publication)
        self.assertEqual(result, {"status": "source_restored", "revision": failed})
        recovery.assert_called_once_with(config=self.config,
                                         publication_file=self.publication,
                                         successor_revision=failed)

    def test_orphan_identity_prevents_any_transition(self):
        (self.directory / ("d" * 40 + auto.IDENTITY_SUFFIX)).write_text("sealed")
        with patch.object(auto.ip_forward_recovery, "recover_locked") as recovery:
            with self.assertRaisesRegex(auto.AutoRecoveryError,
                                        "forward_orphan_identity"):
                auto.recover_locked(config=self.config,
                                    publication_file=self.publication)
        recovery.assert_not_called()

    def test_two_interrupted_receipts_refuse_ambiguous_recovery(self):
        self._receipt("e" * 40)
        self._receipt("f" * 40)
        with patch.object(auto.ip_forward_journal, "ForwardJournal") as journal, \
             patch.object(auto.ip_forward_identity, "read"), \
             patch.object(auto.ip_forward_recovery, "recover_locked") as recovery:
            journal.return_value.read.return_value = {"phase": "exposure_intent"}
            with self.assertRaisesRegex(auto.AutoRecoveryError,
                                        "multiple_interrupted"):
                auto.recover_locked(config=self.config,
                                    publication_file=self.publication)
        recovery.assert_not_called()

    def test_failed_recovery_cannot_report_success(self):
        revision = "1" * 40
        self._receipt(revision)
        with patch.object(auto.ip_forward_journal, "ForwardJournal") as journal, \
             patch.object(auto.ip_forward_identity, "read"), \
             patch.object(auto.ip_forward_recovery, "recover_locked",
                          side_effect=auto.ip_forward_recovery.RecoveryError(
                              "forward_recovery_phase_refused")):
            journal.return_value.read.return_value = {"phase": "writers_stopped"}
            with self.assertRaisesRegex(auto.AutoRecoveryError,
                                        "forward_auto_recovery_failed"):
                auto.recover_locked(config=self.config,
                                    publication_file=self.publication)


if __name__ == "__main__":
    main()
