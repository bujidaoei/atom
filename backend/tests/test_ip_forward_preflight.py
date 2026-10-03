"""Focused failures for the read-only active-generation deployment gate."""

import importlib.util
from contextlib import closing, contextmanager
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
sys.path.insert(0, str(DEPLOY))
spec = importlib.util.spec_from_file_location("ip_forward_preflight",
                                          DEPLOY / "ip_forward_preflight.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

IMAGE = "sha256:" + "b" * 64
CADDY_IMAGE = "sha256:" + "c" * 64


def database(path: Path, *, schema: int = 18, live: bool = False,
             missing_origin: bool = False) -> None:
    with closing(sqlite3.connect(path)) as db:
        db.execute(f"PRAGMA user_version={schema}")
        db.executescript("""
            CREATE TABLE projects (id TEXT PRIMARY KEY, active_run_id TEXT);
            CREATE TABLE revision_attempts (state TEXT);
            CREATE TABLE project_origin_ports (project_id TEXT, purpose TEXT, port INTEGER);
            INSERT INTO projects VALUES ('project-1', NULL);
            INSERT INTO project_origin_ports VALUES ('project-1', 'preview', 20000);
        """)
        if not missing_origin:
            db.execute("INSERT INTO project_origin_ports VALUES ('project-1', 'public', 20001)")
        if live:
            db.execute("UPDATE projects SET active_run_id='running'")
        db.commit()


def service(name: str, ordinal: int, image: str, mounts: list[dict],
            network: str, bindings: dict | None = None,
            readonly: bool = True) -> dict:
    return {"Name": "/" + name, "Id": f"{ordinal:064x}", "Image": image,
            "State": {"Running": True, "Health": {"Status": "healthy"}},
            "Mounts": mounts, "HostConfig": {"NetworkMode": network,
                                            "PortBindings": bindings or {},
                                            "ReadonlyRootfs": readonly}}


def bind(path: Path, destination: str, writable: bool = True) -> dict:
    return {"Type": "bind", "Source": str(path),
            "Destination": destination, "RW": writable}


class ForwardPreflightTest(unittest.TestCase):
    def test_public_gate_holds_host_lock_through_internal_inspection(self):
        state = {"held": False}
        config = SimpleNamespace()

        @contextmanager
        def lock():
            self.assertFalse(state["held"])
            state["held"] = True
            try:
                yield
            finally:
                state["held"] = False

        def inspect(**arguments):
            self.assertTrue(state["held"])
            self.assertIs(arguments["config"], config)
            return {"status": "current_generation_verified"}

        with patch.object(module.protected_cutover, "load_config", return_value=config), \
                patch.object(module.protected_cutover, "host_lock", side_effect=lock), \
                patch.object(module, "_inspect_locked", side_effect=inspect):
            result = module.inspect_current(config_file=Path("/private/config"),
                publication_file=Path("/private/publication"), revision="a" * 40)
        self.assertEqual(result["status"], "current_generation_verified")
        self.assertFalse(state["held"])

    def test_successor_requires_clean_exact_revision_and_image(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source, candidate = root / "source", root / "candidate"
            source.mkdir()
            candidate.mkdir()
            config = SimpleNamespace(backup_root=root / "backups",
                                     docker=Path("/usr/bin/docker"))
            successor = "f" * 40
            successor_image = "sha256:" + "e" * 64
            def command(args):
                return successor if args[-2:] == ["rev-parse", "HEAD"] else ""

            with patch.object(module.protected_cutover, "_command", side_effect=command), \
                    patch.object(module.protected_cutover, "_inspect", return_value={
                        "Id": successor_image,
                        "Config": {"Labels": {"atom.revision": successor}}}):
                result = module._target(config, source=source, revision=successor,
                    image_id=successor_image, current_revision="a" * 40,
                    current_image=IMAGE, candidate=candidate)
                self.assertEqual(result["imageId"], successor_image)
                with patch.object(module.protected_cutover, "_inspect", return_value={
                        "Id": successor_image,
                        "Config": {"Labels": {"atom.revision": "a" * 40}}}):
                    with self.assertRaisesRegex(module.ForwardPreflightError,
                                                "successor_image_mismatch"):
                        module._target(config, source=source, revision=successor,
                            image_id=successor_image, current_revision="a" * 40,
                            current_image=IMAGE, candidate=candidate)
                with patch.object(module.protected_cutover, "_command", return_value="dirty"):
                    with self.assertRaisesRegex(module.ForwardPreflightError,
                                                "successor_revision_mismatch"):
                        module._target(config, source=source, revision=successor,
                            image_id=successor_image, current_revision="a" * 40,
                            current_image=IMAGE, candidate=candidate)

    def test_database_rejects_schema_live_writer_and_incomplete_origin(self):
        for condition, expected in (({"schema": 10}, "schema_mismatch"),
                                    ({"live": True}, "active_project"),
                                    ({"missing_origin": True}, "origin_ledger_incomplete")):
            with self.subTest(condition=condition), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary).resolve() / "atom.db"
                database(path, **condition)
                before = path.read_bytes()
                with self.assertRaisesRegex((module.ForwardPreflightError,
                                             module.protected_cutover.CutoverError), expected):
                    module._active_routes(path, 20000, 20127)
                self.assertEqual(path.read_bytes(), before)

    def test_exact_image_bind_and_origin_port_profiles(self):
        with tempfile.TemporaryDirectory() as temporary:
            candidate = Path(temporary).resolve()
            config = SimpleNamespace(api="atom-candidate", broker="atom-candidate-broker",
                                     network="bridge-test", docker=Path("/usr/bin/docker"),
                                     loopback_port=18081)
            data, broker, caddy = (candidate / name for name in ("data", "broker", "caddy"))
            api = service(config.api, 1, IMAGE, [bind(data, "/data")], "bridge-test",
                          {"80/tcp": [{"HostIp": "127.0.0.1", "HostPort": "18081"}]},
                          readonly=False)
            items = {
                config.api: api,
                config.broker: service(config.broker, 2, IMAGE,
                                       [bind(broker, "/broker")], "container:" + api["Id"]),
                "atom-preview": service("atom-preview", 3, IMAGE,
                                        [bind(data, "/data")], "bridge-test"),
                "atom-public": service("atom-public", 4, IMAGE,
                                       [bind(data, "/data")], "bridge-test"),
                "atom-verifier": service("atom-verifier", 5, IMAGE,
                                         [bind(data, "/data")], "private-test"),
                "atom-tls": service("atom-tls", 6, CADDY_IMAGE,
                                    [bind(caddy, "/etc/caddy", False)], "bridge-test",
                                    {f"{port}/tcp": [{"HostIp": "", "HostPort": str(port)}]
                                     for port in (443, 20000, 20001)}),
            }
            values = {"ATOM_CADDY_IMAGE": "caddy:test", "ATOM_FIRST_PORT": "20000",
                      "ATOM_LAST_PORT": "20001",
                      "ATOM_VERIFIER_NETWORK": "private-test"}

            def inspect(_docker, kind, name):
                return {"Id": CADDY_IMAGE} if kind == "image" else items[name]

            with patch.object(module.protected_cutover, "_inspect", side_effect=inspect):
                self.assertEqual(len(module._services(config, candidate, IMAGE, values)), 6)
                items["atom-public"]["Image"] = CADDY_IMAGE
                with self.assertRaisesRegex(module.ForwardPreflightError,
                                            "active_service_image_or_health_mismatch"):
                    module._services(config, candidate, IMAGE, values)
                items["atom-public"]["Image"] = IMAGE
                items["atom-preview"]["Mounts"][0]["Source"] = str(candidate / "old-data")
                with self.assertRaisesRegex(module.ForwardPreflightError,
                                            "active_service_bind_mismatch"):
                    module._services(config, candidate, IMAGE, values)
                items["atom-preview"]["Mounts"][0]["Source"] = str(data)
                del items["atom-tls"]["HostConfig"]["PortBindings"]["20001/tcp"]
                with self.assertRaisesRegex(module.ForwardPreflightError,
                                            "active_ingress_profile_mismatch"):
                    module._services(config, candidate, IMAGE, values)


if __name__ == "__main__":
    unittest.main()
