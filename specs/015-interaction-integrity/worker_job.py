"""Frame a real registered COS artifact for the exact isolated verifier image.

Output is binary worker input; pipe to the network-disabled worker, never log.
The returned observation must be checked separately; this does not attest or
publish anything and makes no business database mutations.
"""
import argparse
import io
import json
from pathlib import Path
import sqlite3
import struct
import sys
from uuid import uuid4

from app.artifacts import configured_artifact_store
from app.config import get_settings
from app.snapshots import verify_snapshot
from app.verification_contract import capture_contract


def selector(name):
    return f'[data-testid="{name}"]'


def fill(name, value):
    return {'action': 'fill', 'selector': selector(name), 'value': value}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--artifacts', required=True, type=Path)
    parser.add_argument('--index', required=True, type=int, choices=range(4))
    args = parser.parse_args()
    expected = json.loads(args.artifacts.read_text())[args.index]
    settings = get_settings()
    with sqlite3.connect(settings.db_path.as_uri() + '?mode=ro', uri=True) as db:
        row = db.execute('''SELECT r.artifact_key,r.snapshot_revision,a.size
          FROM revision_records r JOIN revision_artifacts a ON a.key=r.artifact_key
          JOIN revision_workspaces w ON w.current_revision_id=r.id
          WHERE r.id=? AND r.project_id=?''', (expected['revision'], expected['project'])).fetchone()
    assert row and row[0] == expected['artifact']
    store = configured_artifact_store(settings, Path('/nonexistent'))
    payload = store.read(row[0])
    assert len(payload) == row[2] and verify_snapshot(io.BytesIO(payload)).revision == row[1]
    if args.index == 0:
        setup = [fill('num-a-input', '2'), fill('num-b-input', '3')]
        trigger, outcome = 'calc-btn', selector('result-value') + '[data-value="5"]'
    elif args.index == 1:
        setup = [{'action': 'click', 'selector': selector(name)} for name in ('btn-2', 'btn-add', 'btn-3')]
        trigger, outcome = 'btn-equals', selector('display') + '[data-value="5"]'
    elif args.index == 2:
        setup = [fill('todo-input', 'Actual worker task')]
        trigger, outcome = 'add-button', selector('todo-item') + '[data-title="Actual worker task"]'
    else:
        setup = [fill('item-input', 'Lunch'), fill('amount-input', '20')]
        trigger, outcome = 'add-btn', selector('total-amount') + '[data-total="20"]'
    contract = capture_contract([{'key': 'primary-mouse-action', 'title': 'Primary action', 'detail': '',
        'checks': [{'type': 'flow', 'setup': setup, 'selector': selector(trigger), 'expect': outcome}]}])
    job = {'routeId': uuid4().hex, 'artifactKey': row[0], 'snapshotRevision': row[1],
           'artifactSize': row[2], 'contractDigest': contract.digest, 'budgetSeconds': 30}
    fields = (json.dumps(job, sort_keys=True, separators=(',', ':')).encode(), contract.canonical, payload)
    sys.stdout.buffer.write(b''.join(struct.pack('>I', len(field)) + field for field in fields))


if __name__ == '__main__':
    main()
