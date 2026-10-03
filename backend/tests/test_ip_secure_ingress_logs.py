"""Root-private ingress-log migration backup remains verified and reusable."""

import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "deploy"))
import ip_caddy_logging  # noqa: E402
import ip_secure_ingress_logs  # noqa: E402


@unittest.skipUnless(os.name == "posix" and os.geteuid() == 0,
                     "root POSIX backup semantics required")
class IngressLogBackupTest(unittest.TestCase):
    def test_seals_exact_pair_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as root:
            config = SimpleNamespace(backup_root=Path(root))
            revision = "a" * 40
            base, active = b"base\n", b"active\n"
            first = ip_secure_ingress_logs._backup_configuration(
                config, revision, base, active)
            self.assertEqual(first, ip_secure_ingress_logs._backup_configuration(
                config, revision, base, active))
            self.assertEqual(first.stat().st_mode & 0o777, 0o700)
            self.assertEqual((first / "Caddyfile.base").stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads((first / "manifest.json").read_text())["revision"], revision)
            (first / "Caddyfile").write_bytes(b"tampered\n")
            with self.assertRaisesRegex(ip_caddy_logging.IngressLogPolicyError,
                                        "ingress_log_backup_mismatch"):
                ip_secure_ingress_logs._backup_configuration(config, revision, base, active)


if __name__ == "__main__":
    unittest.main()
