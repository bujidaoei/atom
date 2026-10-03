"""Focused same-lock stage ordering and pre-exposure recovery faults."""

from pathlib import Path
import sys
from unittest import TestCase, main
from unittest.mock import Mock, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "deploy"))
import ip_forward_capture as capture  # noqa: E402
import ip_forward_stage as stage  # noqa: E402
import ip_forward_writers as writers  # noqa: E402
import protected_cutover  # noqa: E402


class ForwardStageTest(TestCase):
    def setUp(self):
        self.config = protected_cutover.CutoverConfig(
            "api", "broker", Path("/old/data"), Path("/old/broker"),
            Path("/backup"), Path("/state"), "atom", 18080, 18, 3,
            Path("/usr/bin/docker"), Path("/var/run/docker.sock"))
        self.revision, self.successor = "a" * 40, "b" * 40
        self.image = "sha256:" + "c" * 64
        self.active = {"revision": self.revision, "imageId": self.image,
                       "candidateDirectory": "/backup/candidate-aaaaaaaaaaaa",
                       "containerIds": {role: f"{index:064x}" for index, role in
                                        enumerate(("api", "broker", "preview",
                                                   "public", "verifier", "caddy"), 1)}}
        self.publication = {"ATOM_FIRST_PORT": "20000",
                            "ATOM_LAST_PORT": "20127",
                            "ATOM_PUBLIC_IP": "192.0.2.10",
                            "ATOM_ACME_DIRECTORY":
                            "https://acme.example.test/directory"}
        self.stopped = writers.StoppedWriters(
            {role: self.active["containerIds"][role]
             for role in writers.STOP_ORDER})
        self.captured = capture.CapturedGeneration(
            Path("/backup/forward-pre-bbbbbbbbbbbb"),
            Path("/backup/forward-candidate-bbbbbbbbbbbb"),
            "d" * 64, "e" * 64, 62, 72, "f" * 64)
        self.order = []

    def _call(self, *, capture_failure=False):
        controller = Mock()
        controller.transition_base.side_effect = lambda _payload, maintenance: (
            self.order.append("maintenance" if maintenance else "restore") or "e" * 64)
        log = Mock()
        log.advance.side_effect = lambda phase, **kwargs: self.order.append(phase)
        def stop(*_args):
            self.order.append("stop")
            return self.stopped
        def take(**_kwargs):
            self.order.append("capture")
            if capture_failure:
                raise capture.CaptureError("injected_backup_failure")
            return self.captured
        with patch.object(stage.ip_forward_preflight, "_inspect_locked",
                          return_value=self.active) as inspect, \
             patch.object(stage.ip_forward_preflight, "_publication",
                          return_value=self.publication), \
             patch.object(stage.ip_forward_preflight, "_active_routes",
                          return_value=tuple()), \
             patch.object(stage, "_controller", return_value=controller), \
             patch.object(stage.ip_forward_identity, "capture",
                          return_value=Path("/state/identity")), \
             patch.object(stage.ip_forward_identity, "read",
                          return_value={"caddy": {"base": "unused"}}), \
             patch.object(stage.ip_forward_identity, "caddy_bytes",
                          return_value=b"original"), \
             patch.object(stage.ip_forward_journal, "ForwardJournal",
                          return_value=log), \
             patch.object(stage.ip_cutover_apply, "_maintenance_caddyfile",
                          return_value=b"maintenance"), \
             patch.object(stage.ip_cutover_apply, "_maintenance_probe"), \
             patch.object(stage.ip_forward_writers, "stop", side_effect=stop), \
             patch.object(stage.ip_forward_writers, "resume",
                          side_effect=lambda *_: self.order.append("resume")), \
             patch.object(stage.ip_forward_capture, "capture", side_effect=take):
            if capture_failure:
                with self.assertRaisesRegex(stage.StageError,
                                            "forward_stage_failed"):
                    stage.stage_locked(config=self.config,
                        publication_file=Path("/etc/atom/publication"),
                        revision=self.revision,
                        successor_source=Path("/source"),
                        successor_revision=self.successor,
                        successor_image="sha256:" + "d" * 64)
                self.assertEqual(inspect.call_count, 2)
            else:
                result = stage.stage_locked(config=self.config,
                    publication_file=Path("/etc/atom/publication"),
                    revision=self.revision, successor_source=Path("/source"),
                    successor_revision=self.successor,
                    successor_image="sha256:" + "d" * 64)
                self.assertEqual(result.captured, self.captured)
                self.assertEqual(inspect.call_count, 1)

    def test_maintenance_precedes_stop_and_capture(self):
        self._call()
        self.assertLess(self.order.index("maintenance"), self.order.index("stop"))
        self.assertLess(self.order.index("stop"), self.order.index("capture"))
        self.assertEqual(self.order[-1], "captured")

    def test_capture_failure_resumes_source_before_reopening_ingress(self):
        self._call(capture_failure=True)
        self.assertLess(self.order.index("resume"), self.order.index("restore"))
        self.assertEqual(self.order[-1], "source_restored")


if __name__ == "__main__":
    main()
