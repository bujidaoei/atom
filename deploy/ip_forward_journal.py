"""Root-private, fsynced phase journal for a schema-18 forward cutover.

An intent is durable before its corresponding external action. Recovery must
inspect live ingress and exact container IDs; a recorded phase alone never
authorizes restoring an older data generation after exposure was attempted.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat

import ip_forward_identity
import protected_cutover


PHASES = (
    "prepared", "maintenance_intent", "maintenance_verified",
    "writers_intent", "writers_stopped", "captured", "candidate_intent",
    "candidate_ready", "exposure_intent", "awaiting_acceptance",
)
TERMINAL = frozenset({"source_restored", "successor_retained", "accepted"})
FORMAT = 1
MAX_BYTES = 64 * 1024


class JournalError(RuntimeError):
    """Stable, credential-free journal error code."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise JournalError(code)


def _private_directory(directory: Path) -> None:
    _require(directory.is_absolute() and ".." not in directory.parts,
             "invalid_forward_journal_path")
    try:
        protected_cutover._trusted_parents(directory)
        info = directory.lstat()
    except (OSError, protected_cutover.CutoverError) as exc:
        raise JournalError("forward_journal_directory_unavailable") from exc
    _require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0
             and stat.S_IMODE(info.st_mode) == 0o700,
             "insecure_forward_journal_directory")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ForwardJournal:
    """One immutable identity with ordered, crash-durable phase transitions."""

    def __init__(self, config: protected_cutover.CutoverConfig,
                 successor_revision: str):
        _require(protected_cutover.REVISION.fullmatch(successor_revision) is not None,
                 "invalid_forward_revision")
        self.config = config
        self.revision = successor_revision
        self.path = config.state_dir / (successor_revision + ".forward-phase.json")
        self.identity_path = config.state_dir / (successor_revision + ".forward.json")

    def _identity_digest(self) -> str:
        ip_forward_identity.read(self.identity_path, config=self.config,
                                 successor_revision=self.revision)
        return hashlib.sha256(self.identity_path.read_bytes()).hexdigest()

    def read(self) -> dict[str, object] | None:
        _private_directory(self.config.state_dir)
        if not self.path.exists() and not self.path.is_symlink():
            return None
        try:
            info = self.path.lstat()
            _require(stat.S_ISREG(info.st_mode) and info.st_uid == 0
                     and stat.S_IMODE(info.st_mode) == 0o600
                     and 0 < info.st_size <= MAX_BYTES,
                     "insecure_forward_journal")
            record = json.loads(self.path.read_text("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise JournalError("forward_journal_unreadable") from exc
        _require(type(record) is dict and set(record) == {
            "format", "successorRevision", "identitySha256", "phase",
            "events", "capture", "candidate"} and record["format"] == FORMAT
            and record["successorRevision"] == self.revision
            and record["identitySha256"] == self._identity_digest(),
            "forward_journal_identity_mismatch")
        events = record["events"]
        _require(type(events) is list and 1 <= len(events) <= len(PHASES) + 1,
                 "invalid_forward_journal")
        observed_phases = [event.get("phase") for event in events
                           if type(event) is dict]
        _require(type(record["capture"]) is
                 (dict if "captured" in observed_phases else type(None))
                 and type(record["candidate"]) is
                 (dict if "candidate_ready" in observed_phases else type(None)),
                 "invalid_forward_journal")
        seen: list[str] = []
        for event in events:
            _require(type(event) is dict and set(event) == {"phase", "at", "evidence"}
                     and type(event["at"]) is str and bool(event["at"])
                     and type(event["evidence"]) is dict,
                     "invalid_forward_journal")
            phase = event["phase"]
            if phase == "candidate_intent":
                digest = event["evidence"].get("preStartBaselineSha256")
                _require(type(digest) is str and len(digest) == 64
                         and all(char in "0123456789abcdef" for char in digest),
                         "invalid_forward_startup_baseline")
            if phase in PHASES:
                _require(len(seen) < len(PHASES) and phase == PHASES[len(seen)],
                         "invalid_forward_journal_sequence")
            else:
                _require(phase in TERMINAL and len(seen) > 0
                         and len(seen) == len(events) - 1,
                         "invalid_forward_journal_sequence")
                if phase == "source_restored" and "candidate_ready" in seen:
                    _require(event["evidence"].get("writeFence") == "unchanged",
                             "forward_exposure_requires_fence")
                if phase == "accepted":
                    _require(seen[-1] == "awaiting_acceptance",
                             "invalid_forward_journal_sequence")
            seen.append(phase)
        _require(record["phase"] == seen[-1], "invalid_forward_journal")
        if record["capture"] is not None:
            self._validate_capture(record["capture"])
        if record["candidate"] is not None:
            self._validate_candidate(record["candidate"])
        return record

    def _validate_capture(self, capture: object) -> None:
        _require(type(capture) is dict and set(capture) == {
            "backupDirectory", "candidateDirectory", "manifestSha256",
            "caddySha256", "cosInventorySha256", "artifactCount", "originCount"},
            "invalid_forward_capture_receipt")
        identity = ip_forward_identity.read(
            self.identity_path, config=self.config,
            successor_revision=self.revision)
        _require(capture["backupDirectory"] == identity["backupDirectory"]
                 and capture["candidateDirectory"] == identity["candidateDirectory"]
                 and all(type(capture[key]) is str and len(capture[key]) == 64
                         and all(character in "0123456789abcdef"
                                 for character in capture[key])
                         for key in ("manifestSha256", "caddySha256",
                                     "cosInventorySha256"))
                 and all(type(capture[key]) is int and 0 <= capture[key] <= 10000
                         for key in ("artifactCount", "originCount")),
                 "invalid_forward_capture_receipt")

    def _validate_candidate(self, candidate: object) -> None:
        _require(type(candidate) is dict and set(candidate) == {
            "directory", "imageId", "containerIds", "baselineSha256",
            "caddySha256"}, "invalid_forward_candidate_receipt")
        identity = ip_forward_identity.read(
            self.identity_path, config=self.config,
            successor_revision=self.revision)
        ids = candidate["containerIds"]
        _require(candidate["directory"] == identity["candidateDirectory"]
                 and candidate["imageId"] == identity["successorImageId"]
                 and type(ids) is dict and set(ids) == set(ip_forward_identity.ROLES)
                 and all(type(value) is str and len(value) == 64
                         and all(character in "0123456789abcdef"
                                 for character in value) for value in ids.values())
                 and len(set(ids.values())) == len(ids)
                 and not set(ids.values()) & set(identity["containerIds"].values())
                 and all(type(candidate[key]) is str and len(candidate[key]) == 64
                         and all(character in "0123456789abcdef"
                                 for character in candidate[key])
                         for key in ("baselineSha256", "caddySha256")),
                 "invalid_forward_candidate_receipt")

    def _write(self, record: dict[str, object]) -> None:
        _private_directory(self.config.state_dir)
        payload = (json.dumps(record, sort_keys=True, separators=(",", ":"))
                   + "\n").encode("utf-8")
        _require(len(payload) <= MAX_BYTES, "forward_journal_too_large")
        temporary = self.config.state_dir / (
            self.path.name + ".new-" + os.urandom(8).hex())
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                                 | getattr(os, "O_NOFOLLOW", 0), 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            if os.name != "nt":
                descriptor = os.open(self.config.state_dir,
                                     os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
        finally:
            temporary.unlink(missing_ok=True)

    def begin(self) -> dict[str, object]:
        _require(self.read() is None, "forward_journal_exists")
        digest = self._identity_digest()
        record: dict[str, object] = {
            "format": FORMAT, "successorRevision": self.revision,
            "identitySha256": digest, "phase": "prepared", "capture": None,
            "candidate": None,
            "events": [{"phase": "prepared", "at": _utc_now(), "evidence": {}}],
        }
        self._write(record)
        return self.read()

    def advance(self, phase: str, *, evidence: dict[str, object] | None = None,
                capture: dict[str, object] | None = None,
                candidate: dict[str, object] | None = None) -> dict[str, object]:
        record = self.read()
        _require(record is not None, "forward_journal_missing")
        previous = record["phase"]
        _require(type(phase) is str and type(evidence) in (dict, type(None))
                 and (phase in PHASES and previous in PHASES
                      and PHASES.index(phase) == PHASES.index(previous) + 1
                      or phase in TERMINAL and previous in PHASES),
                 "invalid_forward_phase_transition")
        details = evidence or {}
        _require(all(type(key) is str and type(value) in (str, int, bool)
                     for key, value in details.items()), "invalid_forward_evidence")
        if phase == "candidate_intent":
            digest = details.get("preStartBaselineSha256")
            _require(type(digest) is str and len(digest) == 64
                     and all(char in "0123456789abcdef" for char in digest),
                     "invalid_forward_startup_baseline")
        if phase == "captured":
            self._validate_capture(capture)
            record["capture"] = capture
        else:
            _require(capture is None, "unexpected_forward_capture")
        if phase == "candidate_ready":
            self._validate_candidate(candidate)
            record["candidate"] = candidate
        else:
            _require(candidate is None, "unexpected_forward_candidate")
        if phase == "accepted":
            _require(previous == "awaiting_acceptance",
                     "invalid_forward_phase_transition")
        if phase == "source_restored" and previous in PHASES[
                PHASES.index("candidate_ready"):]:
            _require(details.get("writeFence") == "unchanged",
                     "forward_exposure_requires_fence")
        record["phase"] = phase
        record["events"].append({"phase": phase, "at": _utc_now(),
                                 "evidence": details})
        self._write(record)
        return self.read()
