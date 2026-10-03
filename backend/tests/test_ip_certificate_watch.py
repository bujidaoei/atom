"""Focused certificate-watch policy and bounded real-socket failure checks."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import ssl
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "deploy"))
import ip_certificate_watch as watch  # noqa: E402


class CertificateWatchTest(unittest.TestCase):
    def test_healthy_summary_reports_earliest_expiry_without_port_details(self):
        now = datetime(2026, 10, 4, tzinfo=timezone.utc)
        result = watch._summarize((("a" * 64, now + timedelta(hours=50)),
                                   ("a" * 64, now + timedelta(hours=49))), now=now)
        self.assertEqual(result["status"], "certificate_healthy")
        self.assertEqual(result["originCount"], 1)
        self.assertEqual(result["expiresAt"], "2026-10-06T01:00:00Z")
        self.assertEqual(result["fingerprintSha256"], "a" * 64)

    def test_final_36_hours_fail_instead_of_claiming_renewal(self):
        now = datetime(2026, 10, 4, tzinfo=timezone.utc)
        with self.assertRaisesRegex(watch.CertificateWatchError,
                                    "^certificate_renewal_due$"):
            watch._summarize((("a" * 64, now + timedelta(hours=36)),), now=now)

    def test_mixed_fingerprints_fail_before_expiry_status(self):
        now = datetime(2026, 10, 4, tzinfo=timezone.utc)
        with self.assertRaisesRegex(watch.CertificateWatchError,
                                    "^certificate_inconsistent$"):
            watch._summarize((("a" * 64, now + timedelta(days=3)),
                              ("b" * 64, now + timedelta(days=3))), now=now)

    def test_unreachable_socket_fails_with_stable_port_code(self):
        with self.assertRaisesRegex(watch.CertificateWatchError,
                                    "^certificate_probe_failed:1$"):
            watch._probe("127.0.0.1", 1, ssl.create_default_context())

    def test_derives_only_committed_ports_from_verified_generation(self):
        config = SimpleNamespace(docker=Path("/usr/bin/docker"), api="atom-candidate")
        api = {"Name": "/atom-candidate", "State": {"Running": True},
               "Image": "sha256:" + "a" * 64}
        image = {"Id": api["Image"], "Config": {"Labels": {
            "atom.revision": "b" * 40}}}
        active = {"imageId": api["Image"], "candidateDirectory": "/private/current",
                  "activeOriginCount": 2}
        publication = {"ATOM_PUBLIC_IP": "192.0.2.10", "ATOM_FIRST_PORT": "20000",
                       "ATOM_LAST_PORT": "20127"}
        routes = (SimpleNamespace(port=20001), SimpleNamespace(port=20072))
        from contextlib import nullcontext
        with (patch.object(watch.protected_cutover, "load_config", return_value=config),
              patch.object(watch.protected_cutover, "host_lock", return_value=nullcontext()),
              patch.object(watch.ip_origin_reconcile, "_no_interrupted_forward"),
              patch.object(watch.protected_cutover, "_inspect", side_effect=(api, image)),
              patch.object(watch.ip_forward_preflight, "_inspect_locked", return_value=active),
              patch.object(watch.ip_forward_preflight, "_publication", return_value=publication),
              patch.object(watch.ip_forward_preflight, "_active_routes", return_value=routes)):
            self.assertEqual(watch._targets(Path("/config"), Path("/publication")),
                             ("192.0.2.10", (443, 20001, 20072)))


if __name__ == "__main__":
    unittest.main()
