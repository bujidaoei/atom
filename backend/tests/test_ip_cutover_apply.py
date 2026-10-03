"""Focused forward-cutover failover and bounded preflight tests."""

from contextlib import nullcontext
import importlib.util
from pathlib import Path
import socket
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


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
