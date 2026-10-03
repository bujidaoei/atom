"""Interrupted pre-handoff recovery must use the sealed six source IDs."""

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import sys
import tempfile
from unittest import TestCase, main, skipUnless
from unittest.mock import Mock, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "deploy"))
import ip_forward_recovery as recovery  # noqa: E402


class ForwardRecoveryTest(TestCase):
    def setUp(self):
        self.config = Mock()
        self.config.docker = Path("/usr/bin/docker")
        self.config.state_dir = Path("/state")
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

    def _partial_fixture(self):
        temporary = tempfile.TemporaryDirectory(prefix="atom-forward-recover-")
        self.addCleanup(temporary.cleanup)
        candidate = Path(temporary.name).resolve() / "candidate"
        caddy = candidate / "caddy"
        caddy.mkdir(parents=True)
        (caddy / "Caddyfile").write_bytes(b"maintenance")
        (caddy / "Caddyfile").chmod(0o600)
        receipt = dict(self.identity)
        receipt.update({
            "candidateDirectory": str(candidate),
            "backupDirectory": str(candidate.parent / "backup"),
            "successorImageId": "sha256:" + "b" * 64,
            "serviceIps": {"caddy": "172.30.0.4"},
            "heldNames": {role: "held-" + role for role in self.ids},
        })
        self.journal.read.return_value = {
            "phase": "candidate_intent", "capture": {
                "backupDirectory": receipt["backupDirectory"],
                "manifestSha256": "a" * 64,
                "caddySha256": hashlib.sha256(b"maintenance").hexdigest(),
                "artifactCount": 2, "originCount": 4,
                "cosInventorySha256": "c" * 64}}
        return receipt

    def test_partial_handoff_fences_before_cleanup_and_source_restore(self):
        receipt = self._partial_fixture()
        events = []
        with patch.object(recovery.ip_forward_journal, "ForwardJournal",
                          return_value=self.journal), \
             patch.object(recovery.ip_forward_identity, "read",
                          return_value=receipt), \
             patch.object(recovery.ip_forward_preflight, "_publication",
                          return_value={"ATOM_FIRST_PORT": "20000",
                                        "ATOM_LAST_PORT": "20003"}), \
             patch.object(recovery.ip_forward_preflight, "_active_routes",
                          return_value=()), \
             patch.object(recovery, "_candidate_caddy_digest"), \
             patch.object(recovery.ip_forward_stage, "_controller",
                          return_value=Mock()), \
             patch.object(recovery.ip_forward_start,
                          "_fence_partial_candidate",
                          side_effect=lambda **_: events.append("fence")), \
             patch.object(recovery.ip_forward_start, "_cleanup_candidate",
                          side_effect=lambda **_: events.append("cleanup")), \
             patch.object(recovery.ip_forward_hold, "restore",
                          side_effect=lambda **_: events.append("restore")):
            self.assertEqual(recovery.recover_partial_handoff_locked(
                config=self.config, publication_file=self.publication_file,
                successor_revision=self.successor_revision), "source_restored")
        self.assertEqual(events, ["fence", "cleanup", "restore"])

    def test_changed_partial_candidate_is_retained(self):
        receipt = self._partial_fixture()
        with patch.object(recovery.ip_forward_journal, "ForwardJournal",
                          return_value=self.journal), \
             patch.object(recovery.ip_forward_identity, "read",
                          return_value=receipt), \
             patch.object(recovery.ip_forward_preflight, "_publication",
                          return_value={"ATOM_FIRST_PORT": "20000",
                                        "ATOM_LAST_PORT": "20003"}), \
             patch.object(recovery.ip_forward_preflight, "_active_routes",
                          return_value=()), \
             patch.object(recovery, "_candidate_caddy_digest"), \
             patch.object(recovery.ip_forward_stage, "_controller",
                          return_value=Mock()), \
             patch.object(recovery.ip_forward_start,
                          "_fence_partial_candidate",
                          side_effect=recovery.ip_forward_start.StartError(
                              "forward_prestart_writes_detected")), \
             patch.object(recovery.ip_forward_start,
                          "_cleanup_candidate") as cleanup, \
             patch.object(recovery.ip_forward_hold, "restore") as restore:
            with self.assertRaisesRegex(recovery.ip_forward_start.StartError,
                                        "forward_prestart_writes_detected"):
                recovery.recover_partial_handoff_locked(
                    config=self.config, publication_file=self.publication_file,
                    successor_revision=self.successor_revision)
        cleanup.assert_not_called()
        restore.assert_not_called()

    def test_ready_receipt_reconstructs_exact_successor_for_write_fence(self):
        receipt = self._partial_fixture()
        candidate_ids = {role: f"{index + 100:064x}" for index, role in
                         enumerate(recovery.ip_forward_identity.ROLES)}
        record = {"phase": "candidate_ready", "candidate": {
            "containerIds": candidate_ids,
            "baselineSha256": "d" * 64,
            "caddySha256": "e" * 64}}
        stage = Mock()
        stage.journal = self.journal
        prepared = Mock()
        with patch.object(recovery, "_rebuild_context",
                          return_value=(record, receipt, stage, prepared)), \
             patch.object(recovery.ip_forward_exposure,
                          "recover_after_exposure",
                          return_value="successor_retained") as reconcile:
            result = recovery.recover_ready_or_exposed_locked(
                config=self.config, publication_file=self.publication_file,
                successor_revision=self.successor_revision)
        self.assertEqual(result, "successor_retained")
        self.assertEqual(reconcile.call_args.kwargs["started"].ids, candidate_ids)
        self.assertEqual(reconcile.call_args.kwargs["held"].ids, self.ids)
        self.assertEqual(reconcile.call_args.kwargs["started"].baseline_sha256,
                         "d" * 64)

    def test_ready_recovery_refuses_missing_candidate_receipt(self):
        receipt = self._partial_fixture()
        with patch.object(recovery, "_rebuild_context",
                          return_value=({"phase": "candidate_ready",
                                         "candidate": None}, receipt,
                                        Mock(), Mock())), \
             patch.object(recovery.ip_forward_exposure,
                          "recover_after_exposure") as reconcile:
            with self.assertRaisesRegex(recovery.RecoveryError,
                                        "forward_candidate_receipt_missing"):
                recovery.recover_ready_or_exposed_locked(
                    config=self.config,
                    publication_file=self.publication_file,
                    successor_revision=self.successor_revision)
        reconcile.assert_not_called()

    @skipUnless(os.name == "posix" and getattr(os, "geteuid", lambda: -1)() == 0,
                "root POSIX private-file semantics")
    def test_partial_caddy_receipt_refuses_changed_bytes(self):
        receipt = self._partial_fixture()
        candidate = Path(receipt["candidateDirectory"])
        candidate.chmod(0o700)
        (candidate / "caddy").chmod(0o700)
        digest = hashlib.sha256(b"maintenance").hexdigest()
        recovery._candidate_caddy_digest(candidate, digest)
        (candidate / "caddy" / "Caddyfile").write_bytes(b"changed")
        with self.assertRaisesRegex(recovery.RecoveryError,
                                    "forward_candidate_caddy_changed"):
            recovery._candidate_caddy_digest(candidate, digest)


if __name__ == "__main__":
    main()
