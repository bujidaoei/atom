"""Console-proof redaction must survive normal and maintenance Caddy bases."""

from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "deploy"))
import ip_caddy_logging as policy  # noqa: E402
import ip_cutover_apply  # noqa: E402


BASE = (b"{\n  default_sni 192.0.2.10\n  grace_period 5s\n}\n\n"
        b"192.0.2.10 { respond \"ok\" 200 }\n")


class IngressLogPolicyTest(unittest.TestCase):
    def test_secures_normal_base_once_without_changing_site(self):
        secured = policy.secure_base(BASE)
        self.assertEqual(secured.count(policy.PROOF_FILTER.encode()), 1)
        self.assertEqual(policy.secure_base(secured), secured)
        self.assertTrue(secured.endswith(b'192.0.2.10 { respond "ok" 200 }\n'))

    def test_rejects_unbounded_or_conflicting_logger(self):
        for source in (
                BASE.replace(b"  grace_period 5s\n", b""),
                BASE.replace(b"  grace_period 5s\n",
                             b"  grace_period 5s\n  log default { format json }\n"),
                BASE.replace(b"  grace_period 5s\n",
                             b"  grace_period 5s\n  " + policy.PROOF_FILTER.encode() + b"\n")):
            with self.subTest(source=source[:45]), self.assertRaises(
                    policy.IngressLogPolicyError):
                policy.secure_base(source)

    def test_maintenance_base_redacts_the_same_header(self):
        maintenance = ip_cutover_apply._maintenance_caddyfile(
            "192.0.2.10", "https://acme.example.test/directory")
        self.assertEqual(maintenance.count(policy.PROOF_FILTER.encode()), 1)
        self.assertEqual(policy.secure_base(maintenance), maintenance)


if __name__ == "__main__":
    unittest.main()
