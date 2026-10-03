"""Selected fail-closed tests for the host-side origin reconciler."""

from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest import TestCase, main
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "deploy"))
import ip_origin_reconcile as reconcile  # noqa: E402


class OriginReconcileTest(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = SimpleNamespace(state_dir=Path(self.temp.name),
                                      docker=Path("/usr/bin/docker"), api="atom-candidate")
        self.revision = "a" * 40
        self.image = "sha256:" + "b" * 64
        self.ids = {"api": "1" * 64, "caddy": "2" * 64}
        self.active = {"ingressDrift": True, "revision": self.revision,
                       "imageId": self.image, "activeOriginCount": 74,
                       "candidateDirectory": "/backup/candidate",
                       "containerIds": self.ids}
        self.publication_file = Path(self.temp.name) / "publication.env"

    def _inspect(self, _docker, kind, name):
        if kind == "container":
            return {"Name": "/atom-candidate", "State": {"Running": True},
                    "Image": self.image}
        return {"Id": self.image,
                "Config": {"Labels": {"atom.revision": self.revision}}}

    def test_reconciles_only_verified_serving_generation(self):
        controller = Mock()
        controller.reconcile.return_value = "d" * 64
        strict = {"containerIds": self.ids, "caddySha256": "d" * 64,
                  "activeOriginCount": 74}
        with patch.object(reconcile.protected_cutover, "_inspect",
                          side_effect=self._inspect), \
             patch.object(reconcile.ip_forward_preflight, "_inspect_locked",
                          side_effect=[self.active, strict]) as inspect, \
             patch.object(reconcile.ip_forward_preflight, "_publication",
                          return_value={}) as publication, \
             patch.object(reconcile.ip_forward_stage, "_controller",
                          return_value=controller):
            result = reconcile.reconcile_locked(
                config=self.config, publication_file=self.publication_file)
        self.assertEqual(result["status"], "origin_ingress_reconciled")
        self.assertEqual(result["originCount"], 74)
        self.assertEqual(inspect.call_count, 2)
        self.assertTrue(inspect.call_args_list[0].kwargs["allow_ingress_drift"])
        self.assertNotIn("allow_ingress_drift", inspect.call_args_list[1].kwargs)
        publication.assert_called_once()
        controller.reconcile.assert_called_once()

    def test_matching_routes_do_not_reload(self):
        with patch.object(reconcile.protected_cutover, "_inspect",
                          side_effect=self._inspect), \
             patch.object(reconcile.ip_forward_preflight, "_inspect_locked",
                          return_value=self.active | {"ingressDrift": False}), \
             patch.object(reconcile.ip_forward_stage, "_controller") as controller:
            result = reconcile.reconcile_locked(
                config=self.config, publication_file=self.publication_file)
        self.assertEqual(result["status"], "origin_ingress_current")
        controller.assert_not_called()

    def test_interrupted_forward_refuses_before_docker_or_caddy(self):
        (self.config.state_dir /
         ("c" * 40 + ".forward-phase.json")).write_text("sealed")
        journal = Mock()
        journal.read.return_value = {"phase": "writers_intent"}
        with patch.object(reconcile.ip_forward_journal, "ForwardJournal",
                          return_value=journal), \
             patch.object(reconcile.protected_cutover, "_inspect") as inspect:
            with self.assertRaisesRegex(reconcile.OriginReconcileError,
                                        "forward_transaction_incomplete"):
                reconcile.reconcile_locked(config=self.config,
                                           publication_file=self.publication_file)
        inspect.assert_not_called()

    def test_orphan_identity_refuses_before_docker_or_caddy(self):
        (self.config.state_dir / ("c" * 40 + ".forward.json")).write_text("sealed")
        with patch.object(reconcile.protected_cutover, "_inspect") as inspect:
            with self.assertRaisesRegex(reconcile.OriginReconcileError,
                                        "forward_orphan_identity"):
                reconcile.reconcile_locked(config=self.config,
                                           publication_file=self.publication_file)
        inspect.assert_not_called()

    def test_post_reload_exact_identity_mismatch_refuses_success(self):
        controller = Mock()
        controller.reconcile.return_value = "d" * 64
        with patch.object(reconcile.protected_cutover, "_inspect",
                          side_effect=self._inspect), \
             patch.object(reconcile.ip_forward_preflight, "_inspect_locked",
                          side_effect=[self.active,
                                       {"containerIds": {"api": "f" * 64},
                                        "caddySha256": "d" * 64}]), \
             patch.object(reconcile.ip_forward_preflight, "_publication",
                          return_value={}), \
             patch.object(reconcile.ip_forward_stage, "_controller",
                          return_value=controller):
            with self.assertRaisesRegex(reconcile.OriginReconcileError,
                                        "origin_reconcile_verification_failed"):
                reconcile.reconcile_locked(config=self.config,
                                           publication_file=self.publication_file)


if __name__ == "__main__":
    main()
