"""Transport-independent migration invariants over a real revision ledger."""
from dataclasses import dataclass
import sqlite3

import pytest

from app.artifact_transfer import (TransferError, transfer_registered,
                                   verify_registered_remote)
from app.artifacts import _describe
from test_adoption_repository import prepared, snapshot
from test_revision_migrations import legacy


@dataclass
class Local:
    payloads: dict

    def read(self, key):
        return self.payloads[key]


class Destination:
    def __init__(self, after_put=None):
        self.payloads = {}
        self.after_put = after_put

    def put(self, payload):
        artifact = _describe(payload)
        self.payloads[artifact.key] = payload
        if self.after_put:
            self.after_put()
        return artifact

    def read(self, key):
        return self.payloads[key]


def test_registered_inventory_transfers_exact_bytes_and_replays(prepared):
    path, _main, _heat, heat_payload, heat_artifact = prepared
    main_payload, main_artifact = snapshot(b'<html>main</html>')
    local = Local({main_artifact.key: main_payload, heat_artifact.key: heat_payload})
    destination = Destination()
    receipt = transfer_registered(path, local, destination)
    assert receipt.schema_version == 12
    assert receipt.artifact_count == 2 and receipt.artifact_bytes == len(main_payload) + len(heat_payload)
    assert len(receipt.inventory_sha256) == 64
    assert destination.payloads == local.payloads
    assert transfer_registered(path, local, destination) == receipt


def test_corrupt_source_or_remote_ack_cannot_produce_receipt(prepared):
    path, _main, _heat, heat_payload, heat_artifact = prepared
    main_payload, main_artifact = snapshot(b'<html>main</html>')
    local = Local({main_artifact.key: main_payload, heat_artifact.key: heat_payload})
    destination = Destination()
    local.payloads[heat_artifact.key] = b'wrong bytes'
    with pytest.raises(TransferError, match='transfer_(source_mismatch|artifact_unavailable)'):
        transfer_registered(path, local, destination)
    local.payloads[heat_artifact.key] = heat_payload
    destination.read = lambda _key: b'wrong bytes'
    with pytest.raises(TransferError, match='transfer_destination_mismatch'):
        transfer_registered(path, local, destination)


def test_inventory_change_or_capacity_refuses_completion(prepared):
    path, _main, _heat, heat_payload, heat_artifact = prepared
    main_payload, main_artifact = snapshot(b'<html>main</html>')
    local = Local({main_artifact.key: main_payload, heat_artifact.key: heat_payload})
    with pytest.raises(TransferError, match='transfer_capacity'):
        transfer_registered(path, local, Destination(), maximum=1)
    extra_payload, extra = snapshot(b'<html>later</html>')
    changed = False

    def add_record():
        nonlocal changed
        if changed:
            return
        changed = True
        with sqlite3.connect(path) as db:
            db.execute('INSERT INTO revision_artifacts VALUES (?,?,?,1)',
                       (extra.key, extra.revision, extra.size))

    with pytest.raises(TransferError, match='transfer_inventory_changed'):
        transfer_registered(path, local, Destination(add_record))
    assert extra_payload != main_payload


def test_read_only_remote_verification_preserves_inventory(prepared):
    path, _main, _heat, heat_payload, heat_artifact = prepared
    main_payload, main_artifact = snapshot(b'<html>main</html>')
    destination = Destination()
    destination.payloads = {main_artifact.key: main_payload,
                            heat_artifact.key: heat_payload}
    before = dict(destination.payloads)
    receipt = verify_registered_remote(path, destination)
    assert receipt.artifact_count == 2
    assert receipt.artifact_bytes == len(main_payload) + len(heat_payload)
    assert destination.payloads == before
    destination.payloads[heat_artifact.key] = b'corrupt'
    with pytest.raises(TransferError, match='transfer_(artifact_unavailable|destination_mismatch)'):
        verify_registered_remote(path, destination)


def test_read_only_remote_verification_refuses_moving_ledger(prepared):
    path, _main, _heat, heat_payload, heat_artifact = prepared
    main_payload, main_artifact = snapshot(b'<html>main</html>')
    extra_payload, extra = snapshot(b'<html>later</html>')
    destination = Destination()
    destination.payloads = {main_artifact.key: main_payload,
                            heat_artifact.key: heat_payload,
                            extra.key: extra_payload}
    original_read = destination.read
    changed = False

    def read_and_append(key):
        nonlocal changed
        if not changed:
            changed = True
            with sqlite3.connect(path) as db:
                db.execute('INSERT INTO revision_artifacts VALUES (?,?,?,1)',
                           (extra.key, extra.revision, extra.size))
        return original_read(key)

    destination.read = read_and_append
    with pytest.raises(TransferError, match='transfer_inventory_changed'):
        verify_registered_remote(path, destination)
