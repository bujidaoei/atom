"""Interrupted pre-handoff recovery must use the sealed six source IDs."""

from contextlib import contextmanager
from pathlib import Path
import sys
from unittest import TestCase, main
from unittest.mock import Mock, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "deploy"))
import ip_forward_recovery as recovery  # noqa: E402


class ForwardRecoveryTest(TestCase):
    def setUp(self):
        self.config = Mock()
        self.config.docker = Path("/usr/bin/docker")
        self.config.api = "atom-candidate"
        self.config.broker = "atom-candidate-broker"
        self.publication_file = Path.cwd() / "publication.env"
        self.successor_revision = "b" * 40
        self.ids = {role: f"{index:064x}" for index, role in
                    enumerate(recovery.ip_forward_identity.ROLES, start=1)}
        self.identity = {
            "containerIds": self.ids,
            "sourceImageId": "sha256:" + "a" * 64,
            "sourceRevision": "a" * 40,
            "sourceDirectory": "/backup/candidate-source",
        }
        self.journal = Mock()
        self.journal.identity_path = Path("/state/forward.json")
        self.journal.read.return_value = {"phase": "writers_intent"}

    def _inspect(self, _docker, _kind, expected_id):
        role = next(role for role, value in self.ids.items()
                    if value == expected_id)
        return {"Id": expected_id,
                "Name": "/" + recovery.ip_forward_identity._name(
                    self.config, role),
                "State": {"Running": role == "caddy"}}

    def test_partial_writer_stop_restarts_only_sealed_source_ids(self):
        with patch.object(recovery.ip_forward_journal, "ForwardJournal",
                          return_value=self.journal), \
             patch.object(recovery.ip_forward_identity, "read",
                          return_value=self.identity), \
             patch.object(recovery.protected_cutover, "_inspect",
                          side_effect=self._inspect), \
             patch.object(recovery.ip_forward_preflight, "_publication",
                          return_value={}) as publication, \
             patch.object(recovery.ip_forward_stage, "_controller",
                          return_value=Mock()), \
             patch.object(recovery.ip_forward_identity, "caddy_bytes",
                          return_value=b"original"), \
             patch.object(recovery.ip_forward_stage,
                          "_recover_pre_exposure") as restore:
            self.assertEqual(recovery.recover_pre_handoff_locked(
                config=self.config, publication_file=self.publication_file,
                successor_revision=self.successor_revision), "source_restored")
        publication.assert_called_once_with(
            self.publication_file, self.config, self.identity["sourceImageId"])
        self.assertEqual(restore.call_args.kwargs["stopped"].ids,
                         {role: self.ids[role] for role in
                          recovery.ip_forward_writers.STOP_ORDER})
        self.assertEqual(restore.call_args.kwargs["revision"],
                         self.identity["sourceRevision"])

    def test_candidate_handoff_phase_refuses_older_source_restore(self):
        self.journal.read.return_value = {"phase": "candidate_intent"}
        with patch.object(recovery.ip_forward_journal, "ForwardJournal",
                          return_value=self.journal), \
             patch.object(recovery.ip_forward_identity, "read") as identity:
            with self.assertRaisesRegex(recovery.RecoveryError,
                                        "forward_recovery_phase_refused"):
                recovery.recover_pre_handoff_locked(
                    config=self.config, publication_file=self.publication_file,
                    successor_revision=self.successor_revision)
        identity.assert_not_called()

    def test_source_id_change_refuses_before_any_restoration(self):
        def changed(docker, kind, expected_id):
            item = self._inspect(docker, kind, expected_id)
            if expected_id == self.ids["public"]:
                item["Id"] = "f" * 64
            return item

        with patch.object(recovery.ip_forward_journal, "ForwardJournal",
                          return_value=self.journal), \
             patch.object(recovery.ip_forward_identity, "read",
                          return_value=self.identity), \
             patch.object(recovery.protected_cutover, "_inspect",
                          side_effect=changed), \
             patch.object(recovery.ip_forward_stage,
                          "_recover_pre_exposure") as restore:
            with self.assertRaisesRegex(recovery.RecoveryError,
                                        "forward_source_identity_changed"):
                recovery.recover_pre_handoff_locked(
                    config=self.config, publication_file=self.publication_file,
                    successor_revision=self.successor_revision)
        restore.assert_not_called()

    def test_wrapper_keeps_host_lock_for_reconciliation(self):
        held = {"value": False}

        @contextmanager
        def lock():
            held["value"] = True
            try:
                yield
            finally:
                held["value"] = False

        def restore(**_kwargs):
            self.assertTrue(held["value"])
            return "source_restored"

        with patch.object(recovery.protected_cutover, "load_config",
                          return_value=self.config), \
             patch.object(recovery.protected_cutover, "host_lock",
                          side_effect=lock), \
             patch.object(recovery, "recover_pre_handoff_locked",
                          side_effect=restore):
            self.assertEqual(recovery.recover_pre_handoff(
                config_file=Path.cwd() / "config.json",
                publication_file=self.publication_file,
                successor_revision=self.successor_revision), "source_restored")
        self.assertFalse(held["value"])


if __name__ == "__main__":
    main()
