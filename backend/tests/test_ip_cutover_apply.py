"""Focused forward-cutover failover and bounded preflight tests."""

from contextlib import nullcontext
from email.message import Message
import importlib.util
from pathlib import Path
import socket
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError


DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
sys.path.insert(0, str(DEPLOY))
spec = importlib.util.spec_from_file_location("ip_cutover_apply", DEPLOY / "ip_cutover_apply.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


REVISION = "f" * 40
IMAGE = "sha256:" + "b" * 64


class Ledger:
    records = []

    def __init__(self, _directory, _revision):
        self.records = []
        Ledger.records = self.records

    def write(self, *, outcome, image_id, details):
        self.records.append((outcome, image_id, details))

    def read(self):
        if not self.records:
            return None
        outcome, _image, details = self.records[-1]
        return {"outcome": outcome, **details}


class CutoverApplyTest(unittest.TestCase):
    def test_maintenance_base_blocks_console_until_explicit_promotion(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            original = b"159.75.231.98 {\n reverse_proxy atom-candidate:80\n}\n"
            (root / "Caddyfile").write_bytes(original)
            publication = {"ATOM_PUBLIC_IP": "159.75.231.98",
                           "ATOM_ACME_DIRECTORY": "https://acme.example/directory"}
            with patch.object(module, "_private_directory", side_effect=lambda path:
                              path.mkdir(mode=0o700)):
                base, active = module._write_caddy_inputs(root, publication)
            maintenance = base.read_bytes()
            self.assertEqual(active.read_bytes(), maintenance)
            self.assertIn(b"respond", maintenance)
            self.assertIn(b"503", maintenance)
            self.assertNotIn(b"reverse_proxy atom-candidate", maintenance)
            self.assertEqual((root / "caddy" / "Caddyfile.console").read_bytes(), original)
            module._promote_console_base(root)
            self.assertEqual(base.read_bytes(), original)
            self.assertEqual(active.read_bytes(), maintenance)

    def test_maintenance_base_rejects_config_injection(self):
        for address, directory in (("159.75.231.98\nrespond 200", "https://acme.example/d"),
                                   ("159.75.231.98", "https://acme.example/d\nrespond 200")):
            with self.subTest(address=address), self.assertRaisesRegex(
                    module.ApplyError, "invalid_maintenance_config"):
                module._maintenance_caddyfile(address, directory)

    def test_maintenance_probe_requires_503_without_cookie_for_reads_and_writes(self):
        calls = []
        headers = Message()
        headers["Cache-Control"] = "no-store"

        class Opener:
            def open(self, request, timeout):
                calls.append((request.full_url, request.get_method()))
                raise HTTPError(request.full_url, 503, "maintenance", headers, None)

        with patch.object(module, "build_opener", return_value=Opener()):
            module._maintenance_probe("159.75.231.98")
        self.assertEqual([method for _url, method in calls], ["GET", "POST"])
        headers["Set-Cookie"] = "session=unexpected"
        with patch.object(module, "build_opener", return_value=Opener()), \
                self.assertRaisesRegex(module.ApplyError, "maintenance_console_exposed"):
            module._maintenance_probe("159.75.231.98")

    def test_ingress_requires_the_exact_stopped_old_caddy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            old_id = "1" * 64
            for observed in ({"Id": old_id, "State": {"Running": True}},
                             {"Id": "2" * 64, "State": {"Running": False}}):
                with self.subTest(observed=observed), patch.object(
                        module.ip_cutover_rollback, "_inspect", return_value=observed), \
                        patch.object(module, "_command") as command:
                    with self.assertRaisesRegex(module.ApplyError,
                                                "old_ingress_not_quiesced"):
                        module._ingress(root, root / "compose.env", root, {},
                                        SimpleNamespace(), old_id)
                    command.assert_not_called()

    def test_ingress_renames_quiesced_caddy_without_a_second_stop(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            old_id = "1" * 64
            publication = {"ATOM_PUBLIC_IP": "159.75.231.98",
                           "ATOM_PREVIEW_UPSTREAM": "atom-preview:8765",
                           "ATOM_PUBLIC_UPSTREAM": "atom-public:8765",
                           "ATOM_ACME_DIRECTORY": "https://acme.example/directory",
                           "ATOM_FIRST_PORT": "20000", "ATOM_LAST_PORT": "20127"}
            with patch.object(module.ip_cutover_rollback, "_inspect", side_effect=[
                    {"Id": old_id, "State": {"Running": False}},
                    {"State": {"Running": True}}]), patch.object(
                    module, "_command", side_effect=["", "a" * 64]) as command, \
                    patch.object(module, "_compose"):
                self.assertEqual(module._ingress(root, root / "compose.env", root,
                                                  publication, SimpleNamespace(), old_id),
                                 "a" * 64)
            self.assertEqual(command.call_args_list[0].args[0],
                             ["docker", "container", "rename", "atom-tls",
                              "atom-tls-rollback"])

    def _publication_case(self, preview_ip: str, public_ip: str,
                          api_ip: str) -> list[str]:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            policy = root / "policy.json"
            policy.write_text("{}", encoding="utf-8")
            inputs = module.Inputs(root / "protected.json", root / "publication.env",
                                   root / "source", REVISION, IMAGE, "172.19.0.4")
            config = SimpleNamespace(data=root / "data", network="test-network",
                                     api="old-api", broker="old-broker")
            values = {
                "ATOM_PUBLICATION_IMAGE": "atom-test:latest",
                "ATOM_CADDY_IMAGE": "caddy:2", "ATOM_STORAGE_ENV_FILE": str(root / "storage.env"),
                "ATOM_DATA_BIND": str(config.data), "ATOM_PROXY_NETWORK": config.network,
                "ATOM_CADDY_PROXY_IP": "172.19.0.2", "ATOM_PUBLIC_IP": "159.75.231.98",
                "ATOM_FIRST_PORT": "20000", "ATOM_LAST_PORT": "20127",
                "ATOM_VERIFIER_NETWORK": "verifier-private",
                "ATOM_VERIFIER_WORKER_IMAGE": "worker:latest",
                "ATOM_VERIFIER_POLICY_PATH": str(policy),
                "ATOM_VERIFIER_ENV_FILE": str(root / "verifier.env"),
                "ATOM_PREVIEW_UPSTREAM": "atom-preview:8765",
                "ATOM_PUBLIC_UPSTREAM": "atom-public:8765",
                "ATOM_ACME_DIRECTORY": "https://acme.example/directory",
                "ATOM_PREVIEW_SERVICE_IP": preview_ip,
                "ATOM_PUBLIC_SERVICE_IP": public_ip,
                "ATOM_CANDIDATE_API_IP": api_ip,
            }
            with patch.object(module, "_private_env", return_value=values), patch.object(
                    module, "_command", side_effect=lambda args, **_kwargs:
                    IMAGE if args[:3] == ["docker", "image", "inspect"] else ""), patch.object(
                    module, "_candidate_address_free") as address_free, patch.object(
                    module, "_origin_ports_free"), patch.object(
                    module.ip_cutover_rollback, "_inspect", return_value=None):
                module._publication_inputs(inputs, config)
                return [call.args[1] for call in address_free.call_args_list]

    def test_candidate_bridge_addresses_are_distinct_and_reserved(self):
        self.assertEqual(self._publication_case("172.19.0.6", "172.19.0.7", "172.19.0.8"),
                         ["172.19.0.4", "172.19.0.6", "172.19.0.7", "172.19.0.8"])
        with self.assertRaisesRegex(module.ApplyError, "invalid_candidate_bridge_ips"):
            self._publication_case("172.19.0.4", "172.19.0.7", "172.19.0.8")
        with self.assertRaisesRegex(module.ApplyError, "invalid_candidate_bridge_ips"):
            self._publication_case("not-an-ip", "172.19.0.7", "172.19.0.8")

    def test_port_preflight_rejects_an_occupied_listener(self):
        with socket.socket() as listener:
            listener.bind(("0.0.0.0", 0))
            port = listener.getsockname()[1]
            with self.assertRaisesRegex(module.ApplyError, "origin_port_occupied"):
                module._origin_ports_free(port, port)

    def test_invalid_candidate_caddy_ip_rejected_before_docker(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            inputs = module.Inputs(root / "protected.json", root / "publication.env",
                                   root / "source", REVISION, IMAGE, "127.0.0.1")
            with self.assertRaisesRegex(module.ApplyError, "invalid_candidate_caddy_ip"):
                inputs.validate()

    def _failure_case(self, recovery_fails: bool):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            config = SimpleNamespace(state_dir=root, backup_root=root, api="old-api",
                                     broker="old-broker", network="test-network")
            inputs = module.Inputs(root / "protected.json", root / "publication.env",
                                   root / "source", REVISION, IMAGE, "172.19.0.4")
            identity = {"oldImageId": "sha256:" + "a" * 64}
            failure = module.ip_cutover_rollback.RollbackError("recovery_failed")
            with patch.object(module.os, "geteuid", return_value=0, create=True), patch.object(
                    module.protected_cutover, "load_config", return_value=config), patch.object(
                    module.protected_cutover, "host_lock", return_value=nullcontext()), patch.object(
                    module.protected_cutover, "preflight", return_value={
                        "oldImageId": identity["oldImageId"],
                        "backupDirectory": str(root / "pre")}), patch.object(
                    module.protected_cutover, "PhaseLedger", Ledger), patch.object(
                    module, "_publication_inputs", return_value={"ATOM_PUBLIC_IP": "159.75.231.98",
                                                               "ATOM_CADDY_IMAGE": "caddy:2"}), patch.object(
                    module, "_caddy_source", return_value=root / "Caddyfile"), patch.object(
                    module.ip_cutover_rollback, "capture_identity", return_value=identity), patch.object(
                    module, "_hash", return_value="0" * 64), patch.object(
                    module, "_command", side_effect=module.ApplyError("stop_failed")), patch.object(
                    module.ip_cutover_rollback, "rollback",
                    side_effect=failure if recovery_fails else None) as recover:
                with self.assertRaisesRegex(module.ApplyError, "cutover_and_rollback_failed"
                                            if recovery_fails else "cutover_rolled_back"):
                    module.apply(inputs)
                recover.assert_called_once_with(identity,
                                                console_url="https://159.75.231.98/atom/")
            self.assertEqual([entry[0] for entry in Ledger.records],
                             ["preflight_passed", "old_identified",
                              "rollback_failed" if recovery_fails else "rolled_back"])
            self.assertEqual([event["phase"] for event in Ledger.records[-1][2]["phaseHistory"]],
                             [entry[0] for entry in Ledger.records])

    def test_failed_writer_stop_restores_old_pair(self):
        self._failure_case(False)

    def test_failed_recovery_records_retryable_outcome(self):
        self._failure_case(True)


if __name__ == "__main__":
    unittest.main()
