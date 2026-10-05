"""One host lock and ordinary failure ownership for the forward pipeline."""

from contextlib import contextmanager
from pathlib import Path
import sys
from unittest import TestCase, main
from unittest.mock import Mock, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "deploy"))
import ip_forward_transaction as transaction  # noqa: E402
import ip_forward_exposure as exposure  # noqa: E402
import ip_forward_start as starter  # noqa: E402


class ForwardTransactionTest(TestCase):
    def setUp(self):
        self.config = Mock()
        self.stage = Mock()
        self.stage.active = {"imageId": "sha256:" + "a" * 64}
        self.stage.captured.backup = Path("/backup/pre")
        self.stage.journal.identity_path = Path("/state/identity.json")
        self.prepared = Mock()
        self.prepared.directory = Path("/backup/candidate")
        self.values = dict(config=self.config,
                           publication_file=Path.cwd() / "publication.env",
                           source_revision="a" * 40,
                           successor_source=Path.cwd(),
                           successor_revision="b" * 40,
                           successor_image="sha256:" + "b" * 64)
        self.events = []

    def test_success_runs_stages_in_order(self):
        with patch.object(transaction.ip_forward_stage, "stage_locked",
                          side_effect=lambda **_: self.events.append("stage")
                          or self.stage), \
             patch.object(transaction.ip_forward_candidate, "prepare",
                          side_effect=lambda **_: self.events.append("prepare")
                          or self.prepared), \
             patch.object(transaction.ip_forward_hold, "hold",
                          side_effect=lambda **_: self.events.append("hold") or Mock()), \
             patch.object(transaction.ip_forward_start, "start",
                          side_effect=lambda **_: self.events.append("start") or Mock()), \
             patch.object(transaction.ip_forward_exposure, "expose",
                          side_effect=lambda **_: self.events.append("expose")):
            result = transaction.run_locked(**self.values)
        self.assertEqual(self.events, ["stage", "prepare", "hold", "start",
                                       "expose"])
        self.assertEqual(result["status"], "awaiting_acceptance")
        self.assertEqual(result["candidateDirectory"],
                         str(self.prepared.directory))

    def test_preparation_failure_restores_exact_source(self):
        with patch.object(transaction.ip_forward_stage, "stage_locked",
                          return_value=self.stage), \
             patch.object(transaction.ip_forward_candidate, "prepare",
                          side_effect=RuntimeError("injected")), \
             patch.object(transaction.ip_forward_identity, "read",
                          return_value={"caddy": {}}), \
             patch.object(transaction.ip_forward_identity, "caddy_bytes",
                          return_value=b"original"), \
             patch.object(transaction.ip_forward_stage,
                          "_recover_pre_exposure") as recover, \
             patch.object(transaction.ip_forward_hold, "hold") as hold:
            with self.assertRaisesRegex(transaction.TransactionError,
                                        "forward_preparation_failed"):
                transaction.run_locked(**self.values)
        recover.assert_called_once()
        self.assertEqual(recover.call_args.kwargs["revision"],
                         self.values["source_revision"])
        hold.assert_not_called()

    def test_partial_handoff_failure_reconciles_candidate_and_held_source(self):
        self.stage.journal.read.return_value = {"phase": "candidate_intent"}
        with patch.object(transaction.ip_forward_stage, "stage_locked",
                          return_value=self.stage), \
             patch.object(transaction.ip_forward_candidate, "prepare",
                          return_value=self.prepared), \
             patch.object(transaction.ip_forward_hold, "hold",
                          side_effect=RuntimeError("injected")), \
             patch.object(transaction.ip_forward_identity, "read",
                          return_value={"containerIds": {"api": "a" * 64}}), \
             patch.object(transaction.ip_forward_start,
                          "_fence_partial_candidate") as fence, \
             patch.object(transaction.ip_forward_start,
                          "_cleanup_candidate") as cleanup, \
             patch.object(transaction.ip_forward_hold, "restore") as restore:
            with self.assertRaisesRegex(transaction.TransactionError,
                                        "forward_handoff_failed"):
                transaction.run_locked(**self.values)
        fence.assert_called_once()
        self.assertEqual(cleanup.call_args.kwargs["source_ids"],
                         {"api": "a" * 64})
        restore.assert_called_once()

    def test_exposure_failure_fences_ready_candidate_before_source_restore(self):
        self.stage.journal.read.return_value = {"phase": "candidate_ready"}
        with patch.object(transaction.ip_forward_stage, "stage_locked",
                          return_value=self.stage), \
             patch.object(transaction.ip_forward_candidate, "prepare",
                          return_value=self.prepared), \
             patch.object(transaction.ip_forward_hold, "hold",
                          return_value=Mock()), \
             patch.object(transaction.ip_forward_start, "start",
                          return_value=Mock()), \
             patch.object(transaction.ip_forward_exposure, "expose",
                          side_effect=RuntimeError("injected")), \
             patch.object(transaction.ip_forward_exposure,
                          "recover_after_exposure") as recover, \
             patch.object(transaction.ip_forward_start,
                          "_cleanup_candidate") as cleanup:
            with self.assertRaisesRegex(transaction.TransactionError,
                                        "forward_exposure_failed"):
                transaction.run_locked(**self.values)
        recover.assert_called_once()
        cleanup.assert_not_called()

    def test_public_wrapper_keeps_lock_for_entire_phase(self):
        lock = {"held": False}

        @contextmanager
        def exclusive():
            lock["held"] = True
            try:
                yield
            finally:
                lock["held"] = False

        def invoke(**_kwargs):
            self.assertTrue(lock["held"])
            return {"status": "awaiting_acceptance"}

        with patch.object(transaction.protected_cutover, "load_config",
                          return_value=self.config), \
             patch.object(transaction.protected_cutover, "host_lock",
                          side_effect=exclusive), \
             patch.object(transaction, "run_locked", side_effect=invoke):
            result = transaction.run(config_file=Path.cwd() / "config.json",
                **{key: value for key, value in self.values.items()
                   if key != "config"})
        self.assertFalse(lock["held"])
        self.assertEqual(result["status"], "awaiting_acceptance")

    def test_failed_exposure_recovery_is_not_replayed_implicitly(self):
        self.stage.journal.read.return_value = {"phase": "candidate_ready"}
        with patch.object(transaction.ip_forward_stage, "stage_locked",
                          return_value=self.stage), \
             patch.object(transaction.ip_forward_candidate, "prepare",
                          return_value=self.prepared), \
             patch.object(transaction.ip_forward_hold, "hold", return_value=Mock()), \
             patch.object(transaction.ip_forward_start, "start", return_value=Mock()), \
             patch.object(transaction.ip_forward_exposure, "expose",
                          side_effect=exposure.ExposureError(
                              "forward_exposure_recovery_failed")), \
             patch.object(transaction.ip_forward_exposure,
                          "recover_after_exposure") as recover:
            with self.assertRaisesRegex(transaction.TransactionError,
                                        "forward_exposure_recovery_failed"):
                transaction.run_locked(**self.values)
        recover.assert_not_called()

    def test_failed_partial_start_recovery_is_not_replayed(self):
        with patch.object(transaction.ip_forward_stage, "stage_locked",
                          return_value=self.stage), \
             patch.object(transaction.ip_forward_candidate, "prepare",
                          return_value=self.prepared), \
             patch.object(transaction.ip_forward_hold, "hold", return_value=Mock()), \
             patch.object(transaction.ip_forward_start, "start",
                          side_effect=starter.StartError(
                              "forward_candidate_recovery_failed")), \
             patch.object(transaction, "_restore_unexposed") as restore:
            with self.assertRaisesRegex(transaction.TransactionError,
                                        "forward_start_recovery_failed"):
                transaction.run_locked(**self.values)
        restore.assert_not_called()


if __name__ == "__main__":
    main()
