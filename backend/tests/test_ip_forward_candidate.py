"""Separate schema18 candidate inputs preserve a real captured release pair."""

from pathlib import Path
import sqlite3
import sys
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "deploy"))
import ip_forward_candidate as candidate  # noqa: E402
import ip_forward_stage as stage_module  # noqa: E402
import test_ip_forward_capture as capture_fixture  # noqa: E402
REAL_CADDY_IP = candidate._caddy_ip


def _setup(tmp_path, monkeypatch):
    source, config, publication, routes, active, stopped = \
        capture_fixture.fixture(tmp_path)
    capture_fixture.patches(monkeypatch, source, active)
    next_revision = "f" * 40
    captured = capture_fixture.module.capture(
        config=config, active=active, publication=publication,
        stopped=stopped, routes=routes, successor_revision=next_revision)
    successor_image = "sha256:" + "b" * 64
    publication.update({
        "ATOM_CADDY_PROXY_IP": "172.30.0.10",
        "ATOM_VERIFIER_ENV_FILE": str(tmp_path / "verifier.env"),
        "ATOM_VERIFIER_WORKER_IMAGE": "sha256:" + "d" * 64,
        "ATOM_VERIFIER_POLICY_PATH": str(tmp_path / "worker-policy.json"),
    })
    identity = {
        "sourceDirectory": str(source),
        "backupDirectory": str(captured.backup),
        "candidateDirectory": str(captured.candidate),
        "sourceImageId": active["imageId"],
        "successorImageId": successor_image,
        "caddy": {"base": "unused"},
    }
    log = Mock()
    log.read.return_value = {
        "phase": "captured", "capture": stage_module._receipt(captured)}
    log.identity_path = tmp_path / "state" / (next_revision + ".forward.json")
    forward = stage_module.ForwardStage(
        active, publication, routes, stopped, captured, log, Mock())
    monkeypatch.setattr(candidate.ip_forward_identity, "read", lambda *_args,
                        **_kwargs: identity)
    monkeypatch.setattr(candidate.ip_forward_identity, "caddy_bytes",
                        lambda *_args: b"original console base")
    monkeypatch.setattr(candidate, "_caddy_ip", lambda *_args: "172.30.0.10")
    monkeypatch.setattr(candidate, "_private_directory",
                        lambda path, *, create=False:
                        path.mkdir(mode=0o700) if create else None)
    def env_build(**kwargs):
        first, second = (kwargs["output_dir"] / name
                         for name in ("api.env", "broker.env"))
        first.write_text("safe=fixture", encoding="utf-8")
        second.write_text("safe=fixture", encoding="utf-8")
        return first, second
    monkeypatch.setattr(candidate.ip_cutover_env, "build", env_build)
    def compose_env(_publication, directory, _image, _address):
        path = directory / "compose.env"
        path.write_text("safe=fixture", encoding="utf-8")
        return path
    monkeypatch.setattr(candidate.ip_cutover_apply,
                        "_compose_environment", compose_env)
    monkeypatch.setattr(candidate.os, "geteuid", lambda: 0, raising=False)
    return config, forward, successor_image


def test_prepares_maintenance_candidate_without_changing_release_pair(
        tmp_path, monkeypatch):
    config, forward, image = _setup(tmp_path, monkeypatch)
    prepared = candidate.prepare(config=config, stage=forward,
        successor_source=tmp_path / "source", successor_revision="f" * 40,
        successor_image=image)
    assert prepared.directory == forward.captured.candidate
    assert prepared.compose_env.exists() and prepared.api_env.exists()
    assert (prepared.directory / "caddy" / "Caddyfile").read_bytes() == \
        (prepared.directory / "Caddyfile").read_bytes()
    assert b"503" in (prepared.directory / "caddy" / "Caddyfile.base").read_bytes()
    with sqlite3.connect(prepared.directory / "data" / "atom.db") as db:
        assert db.execute("SELECT release_id FROM release_publications").fetchone() \
            == ("release-one",)
    assert candidate.paired_backup.verify(forward.captured.backup)[
        "manifestSha256"] == forward.captured.manifest_sha256


def test_changed_candidate_origin_refuses_before_creating_inputs(
        tmp_path, monkeypatch):
    config, forward, image = _setup(tmp_path, monkeypatch)
    with sqlite3.connect(forward.captured.candidate / "data" / "atom.db") as db:
        db.execute("UPDATE project_origin_ports SET port=20002 WHERE purpose='public'")
        db.commit()
    with pytest.raises((candidate.CandidateError,
                        candidate.paired_backup.BackupError)):
        candidate.prepare(config=config, stage=forward,
            successor_source=tmp_path / "source", successor_revision="f" * 40,
            successor_image=image)
    assert not (forward.captured.candidate / "caddy").exists()
    assert not (forward.captured.candidate / "private-env").exists()


@pytest.mark.parametrize("observed", ["172.30.0.11", "198.51.100.12"])
def test_caddy_trusted_proxy_address_must_match_live_id_and_config(
        tmp_path, monkeypatch, observed):
    config, forward, _image = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(candidate.protected_cutover, "_inspect",
        lambda *_args: {"Id": forward.active["containerIds"]["caddy"],
                       "State": {"Running": True},
                       "NetworkSettings": {"Networks": {
                           config.network: {"IPAddress": observed}}}})
    with pytest.raises(candidate.CandidateError,
                       match="forward_caddy_ip_mismatch"):
        REAL_CADDY_IP(config,
            forward.active["containerIds"]["caddy"], forward.publication)
