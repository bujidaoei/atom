"""Exposure ordering and write-aware recovery without live service mutation."""

from pathlib import Path
import sys
from unittest import TestCase, main
from unittest.mock import Mock, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "deploy"))
import ip_forward_exposure as exposure  # noqa: E402
import ip_forward_start as starter  # noqa: E402
import protected_cutover  # noqa: E402


class ForwardExposureTest(TestCase):
    def setUp(self):
        self.config = protected_cutover.CutoverConfig(
            "atom-api", "atom-broker", Path("/old/data"), Path("/old/broker"),
            Path("/backup"), Path("/state"), "atom-network", 18080,
            18, 3, Path("/usr/bin/docker"), Path("/var/run/docker.sock"))
        self.revision = "b" * 40
        self.image = "sha256:" + "d" * 64
        self.publication_file = Path.cwd() / "publication.env"
        self.receipt = {"base": "unused"}
        self.stage = Mock()
        self.stage.publication = {"ATOM_PUBLIC_IP": "192.0.2.10",
                                  "ATOM_ACME_DIRECTORY": "https://acme.invalid"}
        self.prepared = Mock()
        self.prepared.directory = Path("/private/candidate")
        self.held = Mock()
        self.started = starter.StartedCandidate(
            {"api": "a" * 64}, Path("/state/baseline.json"), "e" * 64,
            "f" * 64)
        self.controller = Mock()
        self.events = []

    def _kwargs(self):
        return dict(config=self.config, stage=self.stage,
                    prepared=self.prepared, held=self.held,
                    started=self.started,
                    successor_revision=self.revision,
                    successor_image=self.image,
                    publication_file=self.publication_file)

    def _patches(self):
        return (patch.object(exposure, "_identity", return_value=self.receipt),
                patch.object(exposure, "_candidate_controller",
                             return_value=self.controller),
                patch.object(exposure.ip_forward_identity, "caddy_bytes",
                             return_value=b"normal"),
                patch.object(exposure.ip_cutover_rollback, "_await_console"),
                patch.object(exposure.ip_cutover_apply,
                             "_maintenance_caddyfile", return_value=b"maintenance"),
                patch.object(exposure.ip_cutover_apply, "_maintenance_probe"))

    def test_intent_precedes_normal_route_and_acceptance_receipt(self):
        phase = {"value": "candidate_ready"}
        self.stage.journal.read.side_effect = lambda: {"phase": phase["value"]}

        def advance(value, **_kwargs):
            self.events.append(value)
            phase["value"] = value

        self.stage.journal.advance.side_effect = advance
        self.controller.transition_base.side_effect = (
            lambda _payload, **_kwargs: self.events.append("normal") or "f" * 64)
        with self._patches()[0], self._patches()[1], self._patches()[2], \
             self._patches()[3]:
            exposure.expose(**self._kwargs())
        self.assertEqual(self.events, ["exposure_intent", "normal",
                                       "awaiting_acceptance"])

    def test_clean_candidate_restores_source_after_writer_exclusion(self):
        self.stage.journal.read.return_value = {"phase": "exposure_intent"}
        self.controller.transition_base.side_effect = (
            lambda _payload, **_kwargs: self.events.append("maintenance"))
        with self._patches()[0], self._patches()[1], self._patches()[4], \
             self._patches()[5], \
             patch.object(exposure.ip_forward_writers, "ensure_stopped",
                          side_effect=lambda *_args: self.events.append("stop")), \
             patch.object(exposure.candidate_write_fence, "compare_baseline",
                          side_effect=lambda *_args, **_kwargs:
                          self.events.append("compare") or True), \
             patch.object(exposure.ip_forward_start, "_cleanup_candidate",
                          side_effect=lambda **_kwargs: self.events.append("cleanup")), \
             patch.object(exposure.ip_forward_hold, "restore",
                          side_effect=lambda **kwargs:
                          self.events.append(("restore", kwargs["write_fence_unchanged"]))):
            outcome = exposure.recover_after_exposure(**self._kwargs())
        self.assertEqual(outcome, "source_restored")
        self.assertEqual(self.events, ["maintenance", "stop", "compare",
                                       "cleanup", ("restore", True)])

    def test_changed_candidate_retains_successor_and_never_restores_source(self):
        self.stage.journal.read.return_value = {"phase": "awaiting_acceptance"}
        self.controller.transition_base.side_effect = (
            lambda payload, **_kwargs: self.events.append(payload))
        with self._patches()[0], self._patches()[1], self._patches()[2], \
             self._patches()[3], self._patches()[4], self._patches()[5], \
             patch.object(exposure.ip_forward_writers, "ensure_stopped",
                          return_value=Mock()), \
             patch.object(exposure.candidate_write_fence, "compare_baseline",
                          return_value=False), \
             patch.object(exposure.ip_forward_writers, "resume",
                          side_effect=lambda *_args: self.events.append("resume")), \
             patch.object(exposure.ip_forward_hold, "restore") as restore:
            outcome = exposure.recover_after_exposure(**self._kwargs())
        self.assertEqual(outcome, "successor_retained")
        self.assertEqual(self.events, [b"maintenance", "resume", b"normal"])
        restore.assert_not_called()
        self.stage.journal.advance.assert_called_once_with(
            "successor_retained", evidence={
                "writeFence": "changed", "successorIdsChecked": True,
                "normalIngressProbed": True})

    def test_unreadable_baseline_retains_successor(self):
        self.stage.journal.read.return_value = {"phase": "exposure_intent"}
        with self._patches()[0], self._patches()[1], self._patches()[2], \
             self._patches()[3], self._patches()[4], self._patches()[5], \
             patch.object(exposure.ip_forward_writers, "ensure_stopped",
                          return_value=Mock()), \
             patch.object(exposure.candidate_write_fence, "compare_baseline",
                          side_effect=exposure.candidate_write_fence.FenceError(
                              "baseline_unavailable")), \
             patch.object(exposure.ip_forward_writers, "resume"), \
             patch.object(exposure.ip_forward_hold, "restore") as restore:
            self.assertEqual(exposure.recover_after_exposure(**self._kwargs()),
                             "successor_retained")
        restore.assert_not_called()
        self.assertEqual(
            self.stage.journal.advance.call_args.kwargs["evidence"]["writeFence"],
            "unverified")

    def test_ready_candidate_write_is_retained_before_exposure_intent(self):
        self.stage.journal.read.return_value = {"phase": "candidate_ready"}
        with self._patches()[0], self._patches()[1], self._patches()[2], \
             self._patches()[3], self._patches()[4], self._patches()[5], \
             patch.object(exposure.ip_forward_writers, "ensure_stopped", return_value=Mock()), \
             patch.object(exposure.candidate_write_fence, "compare_baseline",
                          return_value=False), \
             patch.object(exposure.ip_forward_writers, "resume"), \
             patch.object(exposure.ip_forward_start,
                          "_cleanup_candidate") as cleanup, \
             patch.object(exposure.ip_forward_hold, "restore") as restore:
            self.assertEqual(exposure.recover_after_exposure(**self._kwargs()),
                             "successor_retained")
        cleanup.assert_not_called()
        restore.assert_not_called()
        self.assertEqual(
            self.stage.journal.advance.call_args.kwargs["evidence"]["writeFence"],
            "changed")


if __name__ == "__main__":
    main()
