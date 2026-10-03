"""Rollback protects preserved container IDs before any candidate removal."""

import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
sys.path.insert(0, str(DEPLOY))
spec = importlib.util.spec_from_file_location("ip_cutover_rollback", DEPLOY / "ip_cutover_rollback.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


OLD_IMAGE = "sha256:" + "a" * 64
NEW_IMAGE = "sha256:" + "b" * 64
CADDY_IMAGE = "sha256:" + "c" * 64
IDS = {"api": "1" * 64, "broker": "2" * 64, "caddy": "3" * 64}
IDENTITY = {"oldImageId": OLD_IMAGE, "candidateImageId": NEW_IMAGE,
            "containers": IDS, "names": module.DEFAULT_NAMES}


def container(identity, image, *, project=None, running=False):
    return {"Id": identity, "Image": image, "State": {
        "Running": running, "Health": {"Status": "healthy" if running else "unhealthy"}},
        "Config": {"Labels": {"com.docker.compose.project": project} if project else {}}}


class FakeDocker:
    def __init__(self):
        self.items = {
            "atom-candidate-rollback": container(IDS["api"], OLD_IMAGE),
            "atom-candidate-broker-rollback": container(IDS["broker"], OLD_IMAGE),
            "atom-tls-rollback": container(IDS["caddy"], CADDY_IMAGE),
            "atom-candidate": container("4" * 64, NEW_IMAGE, running=True),
            "atom-candidate-broker": container("5" * 64, NEW_IMAGE, running=True),
            "atom-tls": container("6" * 64, CADDY_IMAGE,
                                  project="atom-ip-ingress", running=True),
            "atom-preview": container("7" * 64, NEW_IMAGE,
                                      project="atom-ip-publication", running=True),
            "atom-public": container("8" * 64, NEW_IMAGE,
                                     project="atom-ip-publication", running=True),
            "atom-verifier": container("9" * 64, NEW_IMAGE,
                                       project="atom-ip-verifier", running=True),
        }
        self.commands = []

    def inspect(self, name):
        return self.items.get(name)

    def run(self, *arguments, **_kwargs):
        self.commands.append(arguments)
        command = arguments[1]
        if command == "stop":
            self.items[arguments[-1]]["State"]["Running"] = False
        elif command == "rm":
            del self.items[arguments[-1]]
        elif command == "rename":
            self.items[arguments[-1]] = self.items.pop(arguments[-2])
        elif command == "start":
            item = self.items[arguments[-1]]
            item["State"] = {"Running": True, "Health": {"Status": "healthy"}}
        else:
            raise AssertionError(arguments)


class RollbackTest(unittest.TestCase):
    def test_namespaced_identity_uses_only_its_own_containers(self):
        prefix = "atom-rollback-drill"
        names = {role: prefix + "-" + role for role in module.DEFAULT_NAMES}
        docker = FakeDocker()
        renamed = {}
        for old_name, item in docker.items.items():
            role = next((key for key, default in module.DEFAULT_NAMES.items()
                         if old_name in (default, default + "-rollback")), None)
            self.assertIsNotNone(role)
            target = names[role] + ("-rollback" if old_name.endswith("-rollback") else "")
            renamed[target] = item
        docker.items = renamed
        identity = IDENTITY | {"names": names}
        with patch.object(module, "_inspect", side_effect=docker.inspect), patch.object(
                module, "_run", side_effect=docker.run), patch.object(module, "_await_console"):
            module.rollback(identity, console_url="https://127.0.0.1:44443/atom/")
        self.assertEqual(docker.items[names["api"]]["Id"], IDS["api"])
        self.assertNotIn("atom-candidate", docker.items)

    def test_rejects_colliding_container_names(self):
        bad = module.DEFAULT_NAMES | {"preview": "atom-candidate-rollback"}
        with self.assertRaisesRegex(module.RollbackError, "invalid_container_names"):
            module._names(bad)

    def test_restores_exact_old_pair_and_removes_only_candidate_services(self):
        docker = FakeDocker()
        with patch.object(module, "_inspect", side_effect=docker.inspect), patch.object(
                module, "_run", side_effect=docker.run), patch.object(
                module, "_await_console") as console:
            module.rollback(IDENTITY, console_url="https://159.75.231.98/atom/")
        console.assert_called_once_with("https://159.75.231.98/atom/", ca_file=None)
        for role, name in module.DEFAULT_CONTAINERS.items():
            self.assertEqual(docker.items[name]["Id"], IDS[role])
            self.assertTrue(docker.items[name]["State"]["Running"])
        self.assertFalse(any(name in docker.items for name in module.DEFAULT_EXTRA.values()))
        self.assertLess(docker.commands.index(("container", "stop", "--time", "90",
                                               "atom-candidate-broker")),
                        docker.commands.index(("container", "stop", "--time", "30",
                                               "atom-candidate")))

    def test_missing_old_identity_rejects_before_removing_candidate(self):
        docker = FakeDocker()
        docker.items["atom-candidate-broker-rollback"]["Id"] = "0" * 64
        with patch.object(module, "_inspect", side_effect=docker.inspect), patch.object(
                module, "_run", side_effect=docker.run):
            with self.assertRaisesRegex(module.RollbackError, "old_container_identity_missing"):
                module.rollback(IDENTITY, console_url="https://159.75.231.98/atom/")
        self.assertEqual(docker.commands, [])

    def test_unknown_candidate_api_rejects_before_removal(self):
        docker = FakeDocker()
        docker.items["atom-candidate"]["Image"] = "sha256:" + "d" * 64
        with patch.object(module, "_inspect", side_effect=docker.inspect), patch.object(
                module, "_run", side_effect=docker.run):
            with self.assertRaisesRegex(module.RollbackError, "candidate_name_conflict"):
                module.rollback(IDENTITY, console_url="https://159.75.231.98/atom/")
        self.assertEqual(docker.commands, [])

    def test_unknown_caddy_or_support_service_rejects_before_removal(self):
        for name in ("atom-tls", "atom-verifier"):
            docker = FakeDocker()
            docker.items[name]["Config"]["Labels"]["com.docker.compose.project"] = "other"
            with self.subTest(name=name), patch.object(
                    module, "_inspect", side_effect=docker.inspect), patch.object(
                    module, "_run", side_effect=docker.run):
                with self.assertRaises(module.RollbackError):
                    module.rollback(IDENTITY, console_url="https://159.75.231.98/atom/")
            self.assertEqual(docker.commands, [])

    def test_console_probe_requires_direct_https_ip_origin(self):
        for url in ("http://159.75.231.98/atom/", "https://example.com/atom/",
                    "https://159.75.231.98:80/atom/", "https://159.75.231.98/other"):
            with self.subTest(url=url), self.assertRaisesRegex(
                    module.RollbackError, "invalid_console_probe"):
                module._await_console(url)


if __name__ == "__main__":
    unittest.main()
