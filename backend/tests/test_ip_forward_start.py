"""Candidate startup gates and failure ordering, without production mutation."""

import hashlib
from pathlib import Path
import sys
import tempfile
from unittest import TestCase, main
from unittest.mock import Mock, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "deploy"))
import ip_forward_candidate as candidate  # noqa: E402
import ip_forward_hold as hold  # noqa: E402
import ip_forward_identity as identity  # noqa: E402
import ip_forward_stage as stage_module  # noqa: E402
import ip_forward_start as starter  # noqa: E402
import ip_forward_writers as writers  # noqa: E402
import protected_cutover  # noqa: E402


class ForwardStartTest(TestCase):
    def setUp(self):
        self.config = protected_cutover.CutoverConfig(
            "atom-api", "atom-broker", Path("/old/data"), Path("/old/broker"),
            Path("/backup"), Path("/state"), "atom-network", 18080,
            18, 3, Path("/usr/bin/docker"), Path("/var/run/docker.sock"))
        self.successor = "b" * 40
        self.image = "sha256:" + "d" * 64
        self.old_ids = {role: f"{index:064x}" for index, role in
                        enumerate(identity.ROLES, 1)}
        self.new_ids = {role: f"{index + 100:064x}" for index, role in
                        enumerate(identity.ROLES, 1)}
        self.names = {role: identity._name(self.config, role) +
                      "-forward-aaaaaaa" for role in identity.ROLES}
        self.addresses = {"api": "172.30.0.8", "preview": "172.30.0.6",
                          "public": "172.30.0.7", "caddy": "172.30.0.4"}
        temporary = tempfile.TemporaryDirectory(prefix="atom-forward-start-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name).resolve()
        (self.directory / "caddy").mkdir()
        (self.directory / "caddy" / "Caddyfile").write_bytes(b"maintenance")
        self.caddy_digest = hashlib.sha256(b"maintenance").hexdigest()
        self.held = hold.HeldSource(self.old_ids, self.names)
        self.prepared = candidate.PreparedCandidate(
            self.directory, Path("/private/compose.env"),
            Path("/private/api.env"), Path("/private/broker.env"),
            self.addresses["caddy"], self.addresses, self.caddy_digest)
        self.publication = {"ATOM_PUBLIC_IP": "192.0.2.10",
                            "ATOM_FIRST_PORT": "20000",
                            "ATOM_LAST_PORT": "20003",
                            "ATOM_VERIFIER_NETWORK": "private",
                            "ATOM_CADDY_IMAGE": "caddy:exact"}
        log = Mock()
        log.read.return_value = {"phase": "candidate_intent"}
        log.identity_path = Path("/state/" + self.successor + ".forward.json")
        self.stage = stage_module.ForwardStage(
            {"containerIds": self.old_ids}, self.publication, (),
            writers.StoppedWriters({role: self.old_ids[role]
                                    for role in writers.STOP_ORDER}),
            Mock(), log, Mock())
        self.receipt = {"containerIds": self.old_ids,
                        "heldNames": self.names, "serviceIps": self.addresses,
                        "candidateDirectory": str(self.directory),
                        "successorImageId": self.image}
        self.events = []

    def _invoke(self, fail_compose: bool = False):
        def compose(_source, _prepared, _revision, filename, *services):
            self.events.append("compose:" + filename)
            if fail_compose and filename == "compose.ip-publication.yml":
                raise starter.StartError("injected_compose_failure")
        def current(_config, role):
            return {"Id": self.new_ids[role], "State": {"Running": True}}
        def profile(*, role, **_kwargs):
            self.events.append("profile:" + role)
            return self.new_ids[role]
        def baseline(*_args, **_kwargs):
            self.events.append("baseline")
            return "e" * 64
        with patch.object(starter.ip_forward_identity, "read",
                          return_value=self.receipt), \
             patch.object(starter, "_confirm_held"), \
             patch.object(starter, "_compose", side_effect=compose), \
             patch.object(starter, "_create_pair",
                          side_effect=lambda *_: self.events.append("pair")), \
             patch.object(starter, "_current", side_effect=current), \
             patch.object(starter, "_profile", side_effect=profile), \
             patch.object(starter, "_wait_healthy"), \
             patch.object(starter.ip_cutover_apply, "_maintenance_probe",
                          side_effect=lambda *_: self.events.append("console_probe")), \
             patch.object(starter, "probe_ip_maintenance_routes",
                          side_effect=lambda *_: self.events.append("origin_probe")), \
             patch.object(starter.ip_forward_preflight, "_active_routes",
                          return_value=()), \
             patch.object(starter.candidate_write_fence, "capture_baseline",
                          side_effect=baseline), \
             patch.object(starter, "_cleanup_candidate",
                          side_effect=lambda **_: self.events.append("cleanup")), \
             patch.object(starter.ip_forward_hold, "restore",
                          side_effect=lambda **_: self.events.append("source_restore")):
            if fail_compose:
                with self.assertRaisesRegex(starter.StartError,
                                            "forward_candidate_start_failed"):
                    starter.start(config=self.config, stage=self.stage,
                        prepared=self.prepared, held=self.held,
                        successor_source=Path.cwd(),
                        successor_revision=self.successor,
                        successor_image=self.image,
                        publication_file=Path.cwd() / "publication.env")
            else:
                result = starter.start(config=self.config, stage=self.stage,
                    prepared=self.prepared, held=self.held,
                    successor_source=Path.cwd(),
                    successor_revision=self.successor,
                    successor_image=self.image,
                    publication_file=Path.cwd() / "publication.env")
                self.assertEqual(result.ids, self.new_ids)

    def test_success_seals_after_health_and_tls_maintenance(self):
        self._invoke()
        self.assertEqual(self.events[:4], [
            "compose:compose.ip-verifier.yml",
            "compose:compose.ip-publication.yml", "pair",
            "compose:compose.ip-ingress.yml"])
        self.assertLess(self.events.index("console_probe"),
                        self.events.index("baseline"))
        self.assertLess(self.events.index("origin_probe"),
                        self.events.index("baseline"))
        event = self.stage.journal.advance.call_args
        self.assertEqual(event.args, ("candidate_ready",))
        self.assertEqual(event.kwargs["candidate"]["containerIds"], self.new_ids)

    def test_failed_support_service_cleans_candidate_before_source_restore(self):
        self._invoke(fail_compose=True)
        self.assertEqual(self.events[-2:], ["cleanup", "source_restore"])
        self.stage.journal.advance.assert_not_called()

    def test_caddy_profile_requires_exact_private_bind_and_public_ports(self):
        item = {"Name": "/atom-tls", "Id": self.new_ids["caddy"],
                "Image": "sha256:" + "c" * 64,
                "Mounts": [{"Destination": "/etc/caddy", "Type": "bind",
                            "Source": str(self.directory / "caddy"), "RW": False}],
                "Config": {"Labels": {"com.docker.compose.project":
                                      starter._project(self.successor)}},
                "State": {"Running": True},
                "NetworkSettings": {"Networks": {self.config.network: {
                    "IPAddress": self.addresses["caddy"],
                    "IPAMConfig": {"IPv4Address": self.addresses["caddy"]}}}},
                "HostConfig": {"NetworkMode": self.config.network,
                               "PortBindings": {
                    "443/tcp": [{"HostIp": "", "HostPort": "443"}],
                    **{f"{port}/tcp": [{"HostIp": "", "HostPort": str(port)}]
                       for port in range(20000, 20004)}}}}
        with patch.object(starter.protected_cutover, "_inspect",
                          return_value={"Id": item["Image"]}):
            self.assertEqual(starter._profile(
                config=self.config, role="caddy", item=item,
                image=self.image, prepared=self.prepared,
                project=starter._project(self.successor),
                publication=self.publication), self.new_ids["caddy"])
            item["HostConfig"]["PortBindings"].pop("20003/tcp")
            with self.assertRaisesRegex(starter.StartError,
                                        "forward_candidate_caddy_ports_mismatch"):
                starter._profile(config=self.config, role="caddy", item=item,
                    image=self.image, prepared=self.prepared,
                    project=starter._project(self.successor),
                    publication=self.publication)
            item["HostConfig"]["PortBindings"]["20003/tcp"] = [
                {"HostIp": "", "HostPort": "20003"}]
            item["Mounts"][0]["Source"] = "/unknown"
            with self.assertRaisesRegex(starter.StartError,
                                        "forward_candidate_bind_mismatch"):
                starter._profile(config=self.config, role="caddy", item=item,
                    image=self.image, prepared=self.prepared,
                    project=starter._project(self.successor),
                    publication=self.publication)


if __name__ == "__main__":
    main()
