"""Selected exact-identity writer quiescence and recovery checks."""

import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch


DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
sys.path.insert(0, str(DEPLOY))
spec = importlib.util.spec_from_file_location("ip_forward_writers",
                                           DEPLOY / "ip_forward_writers.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class FakeDocker:
    def __init__(self, *, fail_role=None, stop_before_failure=False):
        self.ids = {role: f"{index:064x}" for index, role in
                    enumerate(module.STOP_ORDER, start=1)}
        self.running = {role: True for role in module.STOP_ORDER}
        self.actions = []
        self.fail_role = fail_role
        self.stop_before_failure = stop_before_failure

    def inspect(self, _docker, _kind, name):
        names = module.SUPPORT_NAMES | {"api": "atom-candidate",
                                        "broker": "atom-candidate-broker"}
        role = next(role for role, expected in names.items() if expected == name)
        return {"Name": "/" + name, "Id": self.ids[role],
                "State": {"Running": self.running[role],
                          "Health": {"Status": "healthy"}}}

    def run(self, _docker, *args, timeout):
        role = next(role for role, identity in self.ids.items() if identity == args[-1])
        action = args[1]
        self.actions.append((action, role))
        if action == "stop":
            if role != self.fail_role or self.stop_before_failure:
                self.running[role] = False
            if role == self.fail_role:
                raise module.WriterError("writer_docker_unavailable")
        elif action == "start":
            self.running[role] = True
        else:
            raise AssertionError(args)


class ForwardWritersTest(unittest.TestCase):
    def setUp(self):
        # This suite injects the whole database boundary, including its version
        # read; actual v18/v19 files are covered by migration/preflight tests.
        self.enterContext(patch.object(module.forward_schema, 'version', return_value=18))

    def setup(self, fake):
        config = SimpleNamespace(docker=Path("/usr/bin/docker"), api="atom-candidate",
                                 broker="atom-candidate-broker")
        source = Path.cwd() / "isolated-generation"
        return config, source, patch.object(module.protected_cutover, "_inspect",
                                            side_effect=fake.inspect), \
            patch.object(module.protected_cutover, "_database"), \
            patch.object(module, "_run", side_effect=fake.run)

    def test_exact_writer_stop_and_idempotent_resume_order(self):
        fake = FakeDocker()
        config, source, inspect, database, run = self.setup(fake)
        with inspect, database as db, run:
            receipt = module.stop(config, fake.ids, source)
            self.assertEqual(fake.actions, [("stop", role) for role in module.STOP_ORDER])
            self.assertTrue(all(not running for running in fake.running.values()))
            self.assertEqual(db.call_count, 2)
            module.resume(config, receipt)
            module.resume(config, receipt)
        self.assertEqual(fake.actions[5:], [("start", role) for role in
            ("verifier", "api", "broker", "preview", "public")])
        self.assertTrue(all(fake.running.values()))

    def test_resume_starts_dependencies_before_waiting_for_api_health(self):
        fake = FakeDocker()
        fake.running = {role: False for role in module.STOP_ORDER}
        config, source, inspect, database, run = self.setup(fake)

        def healthy(_config, role, _identifier, **_kwargs):
            if role == "api":
                self.assertTrue(fake.running["verifier"])
                self.assertTrue(fake.running["broker"])
            fake.actions.append(("healthy", role))

        with inspect, database, run, patch.object(module, "_healthy",
                                                   side_effect=healthy):
            module.resume(config, module.StoppedWriters(fake.ids))
        self.assertEqual(fake.actions[:5], [("start", role) for role in
            ("verifier", "api", "broker", "preview", "public")])
        self.assertEqual([role for action, role in fake.actions
                          if action == "healthy"],
                         ["verifier", "api", "broker", "preview", "public"])

    def test_resume_rejoins_broker_after_stopped_api(self):
        fake = FakeDocker()
        fake.running["api"] = False
        config, source, inspect, database, run = self.setup(fake)
        with inspect, database, run:
            module.resume(config, module.StoppedWriters(fake.ids))
        self.assertEqual(fake.actions[:3],
                         [("stop", "broker"), ("start", "api"),
                          ("start", "broker")])

    def test_failed_stop_recovers_container_that_stopped_before_timeout(self):
        fake = FakeDocker(fail_role="public", stop_before_failure=True)
        config, source, inspect, database, run = self.setup(fake)
        with inspect, database, run:
            with self.assertRaisesRegex(module.WriterError, "writer_stop_failed"):
                module.stop(config, fake.ids, source)
        self.assertEqual(fake.actions, [("stop", "verifier"), ("stop", "preview"),
                                        ("stop", "public"), ("start", "verifier"),
                                        ("start", "preview"), ("start", "public")])
        self.assertTrue(all(fake.running.values()))

    def test_late_identity_mismatch_recovers_previously_stopped_writers(self):
        fake = FakeDocker()
        config, source, inspect, database, run = self.setup(fake)
        mismatched = dict(fake.ids)
        mismatched["api"] = "f" * 64
        with inspect, database, run:
            with self.assertRaisesRegex(module.WriterError, "writer_stop_failed"):
                module.stop(config, mismatched, source)
        self.assertTrue(all(fake.running.values()))
        self.assertEqual(fake.actions, [("stop", role) for role in module.STOP_ORDER[:-1]]
                         + [("start", role) for role in
                            ("verifier", "broker", "preview", "public")])

    def test_post_stop_database_check_failure_restores_all_writers(self):
        fake = FakeDocker()
        config, source, inspect, database, run = self.setup(fake)
        with inspect, database as db, run:
            db.side_effect = module.protected_cutover.CutoverError("database_integrity_failed")
            with self.assertRaisesRegex(module.WriterError, "writer_stop_failed"):
                module.stop(config, fake.ids, source)
        self.assertEqual(fake.actions, [("stop", role) for role in module.STOP_ORDER]
                         + [("start", role) for role in
                            ("verifier", "api", "broker", "preview", "public")])
        self.assertTrue(all(fake.running.values()))

    def test_stop_failure_after_api_shutdown_starts_dependencies_first(self):
        fake = FakeDocker(fail_role="api", stop_before_failure=True)
        config, source, inspect, database, run = self.setup(fake)

        def healthy(_config, role, _identifier, **_kwargs):
            if role == "api":
                self.assertTrue(fake.running["broker"])
                self.assertTrue(fake.running["verifier"])

        with inspect, database, run, patch.object(module, "_healthy",
                                                   side_effect=healthy):
            with self.assertRaisesRegex(module.WriterError,
                                        "writer_stop_failed"):
                module.stop(config, fake.ids, source)
        self.assertEqual(fake.actions[5:], [("start", role) for role in
            ("verifier", "api", "broker", "preview", "public")])
        self.assertTrue(all(fake.running.values()))

    def test_interrupted_stop_finishes_exact_ids_without_restarting_them(self):
        fake = FakeDocker()
        fake.running["verifier"] = False
        fake.running["preview"] = False
        config, source, inspect, database, run = self.setup(fake)
        with inspect, database as db, run:
            receipt = module.ensure_stopped(config, fake.ids, source)
            module.ensure_stopped(config, fake.ids, source)
        self.assertEqual(receipt.ids, fake.ids)
        self.assertEqual(fake.actions, [("stop", role) for role in
                                        module.STOP_ORDER[2:]])
        self.assertEqual(db.call_count, 4)
        self.assertTrue(all(not running for running in fake.running.values()))

    def test_interrupted_stop_failure_leaves_other_writers_fenced(self):
        fake = FakeDocker(fail_role="public", stop_before_failure=True)
        config, source, inspect, database, run = self.setup(fake)
        with inspect, database, run:
            with self.assertRaisesRegex(module.WriterError,
                                        "writer_docker_unavailable"):
                module.ensure_stopped(config, fake.ids, source)
        self.assertFalse(fake.running["verifier"])
        self.assertFalse(fake.running["preview"])
        self.assertFalse(fake.running["public"])
        self.assertNotIn(("start", "verifier"), fake.actions)


if __name__ == "__main__":
    unittest.main()
