"""Opt-in real Docker proof for partially held source names.

The six disposable containers have no network or host ports. The test never
uses production container names and removes only identities it created.
"""

from pathlib import Path
import os
import secrets
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "deploy"))
import ip_forward_hold as hold  # noqa: E402
import ip_forward_identity as identity  # noqa: E402


@unittest.skipUnless(os.environ.get("ATOM_REAL_DOCKER_DRILL") == "1",
                     "explicit real Docker drill opt-in required")
class ForwardHoldDockerTest(unittest.TestCase):
    def test_partial_name_handoff_restores_exact_six_ids(self):
        docker = Path(os.environ.get("ATOM_DOCKER_BINARY", "/usr/bin/docker"))
        image = os.environ.get("ATOM_DRILL_IMAGE", "python:3.12-slim-bookworm")
        nonce = secrets.token_hex(5)
        names = {role: f"atom-drill-hold-{nonce}-{role}"
                 for role in identity.ROLES}
        held = {role: name + "-held" for role, name in names.items()}
        created: dict[str, str] = {}

        def run(*args: str, timeout: int = 35) -> str:
            result = subprocess.run([str(docker), *args], text=True,
                                    capture_output=True, timeout=timeout,
                                    check=False)
            self.assertEqual(result.returncode, 0,
                             f"docker {args[0]} failed: {result.stderr[:300]}")
            return result.stdout.strip()

        try:
            image_id = run("image", "inspect", image, "--format", "{{.Id}}")
            self.assertRegex(image_id, r"\Asha256:[0-9a-f]{64}\Z")
            for role, name in names.items():
                container_id = run("run", "-d", "--network", "none",
                                   "--read-only", "--name", name, image_id,
                                   "sleep", "600")
                self.assertRegex(container_id, r"\A[0-9a-f]{64}\Z")
                created[role] = container_id
            self.assertEqual(len(set(created.values())), len(identity.ROLES))
            for container_id in created.values():
                run("container", "stop", "--time", "1", container_id)
            # Simulate a process crash after a prefix of source names moved.
            for role in ("api", "broker", "preview"):
                run("container", "rename", created[role], held[role])
            config = SimpleNamespace(docker=docker, api=names["api"],
                                     broker=names["broker"])
            receipt = {"containerIds": created, "heldNames": held,
                       "sourceRevision": "a" * 40}
            stage = SimpleNamespace(stopped=object(), controller=object(),
                                    journal=object(), active={})
            publication = Path.cwd() / "unused-private-publication.env"
            with patch.dict(identity.SUPPORT_NAMES,
                            {role: names[role] for role in
                             ("preview", "public", "verifier", "caddy")}), \
                 patch.object(hold.ip_forward_stage,
                              "_recover_pre_exposure") as recovery, \
                 patch.object(identity, "caddy_bytes", return_value=b"base"):
                hold.restore(config=config, stage=stage, identity=receipt,
                             publication_file=publication)
                hold.restore(config=config, stage=stage, identity=receipt,
                             publication_file=publication)
                self.assertEqual(recovery.call_count, 2)
            for role, container_id in created.items():
                item = run("container", "inspect", container_id,
                           "--format", "{{.Id}} {{.Name}} {{.State.Running}}")
                self.assertEqual(item, f"{container_id} /{names[role]} "
                                 + ("true" if role == "caddy" else "false"))
        finally:
            for container_id in created.values():
                if container_id:
                    subprocess.run([str(docker), "container", "rm", "-f",
                                    container_id], capture_output=True,
                                   timeout=20, check=False)


if __name__ == "__main__":
    unittest.main()
