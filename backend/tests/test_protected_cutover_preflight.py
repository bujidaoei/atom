"""Dependency-free deployment preflight tests for Windows and target Linux."""

import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "protected_cutover.py"
spec = importlib.util.spec_from_file_location("protected_cutover", SCRIPT)
cutover = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = cutover
spec.loader.exec_module(cutover)


def config(root: Path) -> dict:
    roots = [root / name for name in ("data", "broker", "backup", "state")]
    return {
        "schemaVersion": 1,
        "apiContainer": "atom-api",
        "brokerContainer": "atom-broker",
        "dataDirectory": str(roots[0]),
        "brokerDataDirectory": str(roots[1]),
        "backupRoot": str(roots[2]),
        "stateDirectory": str(roots[3]),
        "network": "isolated-network",
        "loopbackPort": 18081,
        "applicationSchema": 10,
        "brokerSchema": 3,
        "dockerBinary": str(root / "docker"),
        "dockerSocket": str(root / "docker.sock"),
    }


class ProtectedCutoverPreflightTest(unittest.TestCase):
    def test_config_rejects_unknown_fields_overlap_and_invalid_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            valid = config(Path(temporary))
            parsed = cutover.CutoverConfig.parse(valid)
            self.assertEqual((parsed.loopback_port, parsed.app_schema), (18081, 10))
            cases = [
                (valid | {"unexpected": "ignored"}, "invalid_config_fields"),
                (valid | {"schemaVersion": True}, "invalid_config_version"),
                (valid | {"apiContainer": "atom;rm"}, "invalid_api_container"),
                (valid | {"brokerContainer": valid["apiContainer"]},
                 "invalid_broker_container"),
                (valid | {"loopbackPort": 80}, "invalid_loopback_port"),
                (valid | {"applicationSchema": False}, "invalid_expected_schema"),
                (valid | {"stateDirectory": str(Path(valid["dataDirectory"]) / "nested")},
                 "overlapping_cutover_directories"),
            ]
            for raw, reason in cases:
                with self.subTest(reason=reason), self.assertRaisesRegex(
                        cutover.CutoverError, reason):
                    cutover.CutoverConfig.parse(raw)

    @unittest.skipUnless(sys.platform == "linux" and
                         getattr(os, "geteuid", lambda: -1)() == 0,
                         "root-owned durable state requires target Linux")
    def test_root_private_status_is_atomic_and_terminal(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "state"
            revision = "a" * 40
            image = "sha256:" + "b" * 64
            ledger = cutover.PhaseLedger(directory, revision)
            with self.assertRaisesRegex(cutover.CutoverError,
                                        "missing_state_directory"):
                ledger.read()
            ledger.write(outcome="preflight_passed", image_id=image,
                         details={"oldImageId": "sha256:" + "c" * 64})
            self.assertEqual(ledger.read()["outcome"], "preflight_passed")
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(ledger.path.stat().st_mode), 0o600)
            self.assertEqual(json.loads(ledger.path.read_text())["imageId"], image)
            self.assertEqual(sorted(path.name for path in directory.iterdir()),
                             [revision + ".json"])
            with self.assertRaisesRegex(cutover.CutoverError,
                                        "status_image_mismatch"):
                ledger.write(outcome="preflight_passed",
                             image_id="sha256:" + "d" * 64, details={})
            with self.assertRaisesRegex(cutover.CutoverError,
                                        "invalid_status_details"):
                ledger.write(outcome="completed", image_id=image,
                             details={"outcome": "forged"})
            ledger.write(outcome="completed", image_id=image,
                         details={"generation": 1})
            with self.assertRaisesRegex(cutover.CutoverError,
                                        "terminal_status_exists"):
                ledger.write(outcome="preflight_passed", image_id=image, details={})
            self.assertEqual(ledger.read()["outcome"], "completed")

    @unittest.skipUnless(sys.platform == "linux" and
                         getattr(os, "geteuid", lambda: -1)() == 0,
                         "root ownership check requires target Linux")
    def test_config_file_requires_root_only_mode(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "cutover.json"
            path.write_text(json.dumps(config(Path(temporary))))
            path.chmod(0o644)
            with self.assertRaisesRegex(cutover.CutoverError,
                                        "insecure_config_file"):
                cutover.load_config(path)
            path.chmod(0o600)
            self.assertEqual(cutover.load_config(path).network, "isolated-network")
            Path(temporary).chmod(0o777)
            with self.assertRaisesRegex(cutover.CutoverError,
                                        "insecure_parent_directory"):
                cutover.load_config(path)


if __name__ == "__main__":
    unittest.main()
