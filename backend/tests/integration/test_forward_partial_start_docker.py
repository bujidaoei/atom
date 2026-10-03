"""Opt-in real Docker test of partial successor fencing and cleanup.

Creates a private bridge and two uniquely named sleeper containers. It never
uses production service names, host ports, databases or object storage.
"""

import ipaddress
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "deploy"))
import ip_forward_identity as identity  # noqa: E402
import ip_forward_start as start  # noqa: E402


@unittest.skipUnless(os.environ.get("ATOM_REAL_DOCKER_DRILL") == "1",
                     "explicit real Docker drill opt-in required")
class ForwardPartialStartDockerTest(unittest.TestCase):
    def test_started_writers_are_fenced_before_baseline_decision(self):
        docker = Path(os.environ.get("ATOM_DOCKER_BINARY", "/usr/bin/docker"))
        image = os.environ.get("ATOM_DRILL_IMAGE", "python:3.12-slim-bookworm")
        nonce = secrets.token_hex(5)
        network = f"atom-drill-fence-{nonce}"
        names = {role: f"atom-drill-fence-{nonce}-{role}"
                 for role in identity.ROLES}
        created: list[str] = []
        network_created = False

        def run(*args: str, timeout: int = 35) -> str:
            result = subprocess.run([str(docker), *args], text=True,
                                    capture_output=True, timeout=timeout,
                                    check=False)
            self.assertEqual(result.returncode, 0,
                             f"docker {args[0]} failed: {result.stderr[:300]}")
            return result.stdout.strip()

        with tempfile.TemporaryDirectory(prefix="atom-forward-fence-") as temp:
            directory = Path(temp).resolve()
            (directory / "data").mkdir()
            try:
                image_id = run("image", "inspect", image, "--format", "{{.Id}}")
                self.assertRegex(image_id, r"\Asha256:[0-9a-f]{64}\Z")
                run("network", "create", "--internal", network)
                network_created = True
                raw = run("network", "inspect", network,
                          "--format", "{{json .IPAM.Config}}")
                subnet = ipaddress.ip_network(json.loads(raw)[0]["Subnet"])
                self.assertEqual(subnet.version, 4)
                addresses = {"preview": str(subnet.network_address + 10),
                             "public": str(subnet.network_address + 11)}
                revision = "b" * 40
                project = start._project(revision)

                def create(role: str, label: str) -> str:
                    container_id = run("run", "-d", "--name", names[role],
                        "--network", network, "--ip", addresses[role],
                        "--read-only", "--label",
                        f"com.docker.compose.project={label}",
                        "--volume", f"{directory / 'data'}:/data", image_id,
                        "sleep", "600")
                    self.assertRegex(container_id, r"\A[0-9a-f]{64}\Z")
                    created.append(container_id)
                    return container_id

                first = {role: create(role, project)
                         for role in ("preview", "public")}
                config = SimpleNamespace(docker=docker, api=names["api"],
                                         broker=names["broker"], network=network)
                prepared = SimpleNamespace(directory=directory,
                                           service_ips=addresses)
                record = {"phase": "candidate_intent", "events": [{
                    "phase": "candidate_intent", "evidence": {
                        "preStartBaselineSha256": "e" * 64}}]}
                stage = SimpleNamespace(journal=SimpleNamespace(
                    read=lambda: record), publication={})
                source_ids = {role: f"{index:064x}" for index, role in
                              enumerate(identity.ROLES, 1)}
                args = dict(config=config, stage=stage, prepared=prepared,
                            successor_revision=revision,
                            successor_image=image_id, source_ids=source_ids)
                with patch.dict(identity.SUPPORT_NAMES,
                                {role: names[role] for role in
                                 ("preview", "public", "verifier", "caddy")}), \
                     patch.object(start.candidate_write_fence,
                                  "compare_baseline", return_value=False):
                    with self.assertRaisesRegex(start.StartError,
                                                "forward_prestart_writes_detected"):
                        start._fence_partial_candidate(**args)
                for role, container_id in first.items():
                    item = run("container", "inspect", container_id,
                               "--format", "{{.Id}} {{.State.Running}}")
                    self.assertEqual(item, container_id + " false", role)
                with patch.dict(identity.SUPPORT_NAMES,
                                {role: names[role] for role in
                                 ("preview", "public", "verifier", "caddy")}), \
                     patch.object(start.candidate_write_fence,
                                  "compare_baseline", return_value=True):
                    start._fence_partial_candidate(**args)
                    start._cleanup_candidate(config=config, prepared=prepared,
                        image=image_id, project=project, publication={},
                        source_ids=source_ids)
                for role in first:
                    self.assertIsNone(start.ip_cutover_rollback._inspect(names[role]))
                foreign = create("preview", "foreign-project")
                with patch.dict(identity.SUPPORT_NAMES,
                                {role: names[role] for role in
                                 ("preview", "public", "verifier", "caddy")}):
                    with self.assertRaisesRegex(start.StartError,
                                                "forward_candidate_project_mismatch"):
                        start._cleanup_candidate(config=config, prepared=prepared,
                            image=image_id, project=project, publication={},
                            source_ids=source_ids)
                self.assertEqual(run("container", "inspect", foreign,
                                     "--format", "{{.Id}}"), foreign)
            finally:
                for container_id in created:
                    subprocess.run([str(docker), "container", "rm", "-f",
                                    container_id], capture_output=True,
                                   timeout=20, check=False)
                if network_created:
                    subprocess.run([str(docker), "network", "rm", network],
                                   capture_output=True, timeout=20,
                                   check=False)


if __name__ == "__main__":
    unittest.main()
