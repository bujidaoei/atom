"""Rollback protects preserved container IDs before any candidate removal."""

from contextlib import closing, nullcontext, redirect_stdout
import importlib.util
import io
from pathlib import Path
import sqlite3
import sys
import tempfile
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
            "containers": IDS, "names": module.DEFAULT_NAMES,
            "stateDirectory": "/private", "revision": "f" * 40}
BASELINE = {"candidateDirectory": "/private/candidate", "stateSha256": "a" * 64}


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
    def test_manual_rollback_preserves_forward_phase_history(self):
        class Ledger:
            latest = {"phaseHistory": [{"phase": "awaiting_acceptance"}]}

            def __init__(self, _directory, _revision):
                pass

            def read(self):
                return Ledger.latest

            def write(self, *, outcome, image_id, details):
                Ledger.latest = {"outcome": outcome, "imageId": image_id, **details}

        identity = IDENTITY | {"revision": "f" * 40, "stateDirectory": "/private"}
        with patch.object(module, "host_lock", return_value=nullcontext()), patch.object(
                module, "_identity", return_value=identity), patch.object(
                module, "PhaseLedger", Ledger), patch.object(module, "rollback") as recover, \
                redirect_stdout(io.StringIO()):
            result = module.main(["rollback", "--identity", "/private/identity.json",
                                  "--console-url", "https://159.75.231.98/atom/"])
        self.assertEqual(result, 0)
        recover.assert_called_once()
        self.assertEqual([event["phase"] for event in Ledger.latest["phaseHistory"]],
                         ["awaiting_acceptance", "rollback_started", "rolled_back"])

    def test_failed_manual_rollback_retains_forward_history(self):
        class Ledger:
            latest = {"phaseHistory": [{"phase": "awaiting_acceptance"}]}

            def __init__(self, _directory, _revision):
                pass

            def read(self):
                return Ledger.latest

            def write(self, *, outcome, image_id, details):
                Ledger.latest = {"outcome": outcome, "imageId": image_id, **details}

        identity = IDENTITY | {"revision": "f" * 40, "stateDirectory": "/private"}
        with patch.object(module, "host_lock", return_value=nullcontext()), patch.object(
                module, "_identity", return_value=identity), patch.object(
                module, "PhaseLedger", Ledger), patch.object(
                module, "rollback", side_effect=module.RollbackError("restore_failed")), \
                redirect_stdout(io.StringIO()), patch("sys.stderr", io.StringIO()):
            result = module.main(["rollback", "--identity", "/private/identity.json",
                                  "--console-url", "https://159.75.231.98/atom/"])
        self.assertEqual(result, 2)
        self.assertEqual([event["phase"] for event in Ledger.latest["phaseHistory"]],
                         ["awaiting_acceptance", "rollback_started", "rollback_failed"])

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
            with patch.object(module, "_baseline", return_value=BASELINE), patch.object(
                    module.candidate_write_fence, "candidate_fingerprint",
                    return_value=BASELINE["stateSha256"]):
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
                module, "_await_console") as console, patch.object(
                module, "_baseline", return_value=BASELINE), patch.object(
                module.candidate_write_fence, "candidate_fingerprint",
                return_value=BASELINE["stateSha256"]):
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

    def test_missing_baseline_refuses_exposed_candidate_without_stopping_it(self):
        docker = FakeDocker()
        with patch.object(module, "_inspect", side_effect=docker.inspect), patch.object(
                module, "_run", side_effect=docker.run), patch.object(
                module, "_baseline", side_effect=module.RollbackError(
                    "candidate_baseline_missing")):
            with self.assertRaisesRegex(module.RollbackError,
                                        "candidate_baseline_missing"):
                module.rollback(IDENTITY, console_url="https://159.75.231.98/atom/")
        self.assertEqual(docker.commands, [])

    def test_post_activation_write_refuses_old_database_and_resumes_candidate(self):
        docker = FakeDocker()
        with patch.object(module, "_inspect", side_effect=docker.inspect), patch.object(
                module, "_run", side_effect=docker.run), patch.object(
                module, "_baseline", return_value=BASELINE), patch.object(
                module.candidate_write_fence, "candidate_fingerprint",
                return_value="b" * 64), patch.object(module, "_await_console") as console:
            with self.assertRaisesRegex(module.RollbackError,
                                        "candidate_has_unmerged_writes"):
                module.rollback(IDENTITY, console_url="https://159.75.231.98/atom/")
        self.assertEqual(docker.items["atom-candidate"]["Id"], "4" * 64)
        self.assertTrue(docker.items["atom-candidate"]["State"]["Running"])
        self.assertTrue(docker.items["atom-tls"]["State"]["Running"])
        self.assertEqual(docker.items["atom-candidate-rollback"]["Id"], IDS["api"])
        self.assertFalse(any(command[1] in ("rm", "rename") for command in docker.commands))
        console.assert_called_once()

    def test_write_during_stop_is_seen_before_old_pair_promotion(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / "data").mkdir()
            (root / "broker").mkdir()
            for path in (root / "data" / "atom.db", root / "broker" / "registry.db"):
                with closing(sqlite3.connect(path)) as db, db:
                    db.execute("CREATE TABLE user_state(id INTEGER PRIMARY KEY)")
            digest = module.candidate_write_fence.candidate_fingerprint(root)
            docker = FakeDocker()
            original_run = docker.run

            def raced_run(*args, **kwargs):
                if args[:2] == ("container", "stop") and args[-1] == "atom-candidate":
                    with closing(sqlite3.connect(root / "data" / "atom.db")) as db, db:
                        db.execute("INSERT INTO user_state VALUES (1)")
                return original_run(*args, **kwargs)

            with patch.object(module, "_inspect", side_effect=docker.inspect), patch.object(
                    module, "_run", side_effect=raced_run), patch.object(
                    module, "_baseline", return_value={
                        "candidateDirectory": str(root), "stateSha256": digest}), patch.object(
                    module, "_await_console"):
                with self.assertRaisesRegex(module.RollbackError,
                                            "candidate_has_unmerged_writes"):
                    module.rollback(IDENTITY, console_url="https://159.75.231.98/atom/")
            self.assertEqual(docker.items["atom-candidate"]["Id"], "4" * 64)
            self.assertTrue(docker.items["atom-candidate"]["State"]["Running"])
            self.assertFalse(any(command[1] == "rm" for command in docker.commands))

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
