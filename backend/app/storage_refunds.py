"""Explicit, append-only compensation for proved pre-dispatch storage failures."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3

from .migrations import MigrationError, backup_database, verify

_REASON = 'storage_preparation_refund'
_ERRORS = {'artifact_io_error', 'artifact_credentials_invalid', 'artifact_access_denied',
           'artifact_signature_invalid', 'artifact_transport_timeout'}


class StorageRefundError(RuntimeError):
    pass


def refund_storage_failures(database: Path, run_ids: tuple[str, ...]):
    if (not database.is_absolute() or not 1 <= len(run_ids) <= 16
            or len(set(run_ids)) != len(run_ids)
            or any(type(run) is not str or re.fullmatch(r'[0-9a-f]{32}', run) is None for run in run_ids)):
        raise StorageRefundError('invalid_storage_refund_request')
    if verify(database) not in range(10, 20):
        raise StorageRefundError('unsupported_storage_refund_schema')
    refunded = duplicate = total = 0
    with closing(sqlite3.connect(database.as_uri() + '?mode=rw', uri=True,
            timeout=3, isolation_level=None)) as db:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE')
        try:
            for run in run_ids:
                row = db.execute('SELECT p.user_id,r.status,r.phase,r.error,r.input_tokens,r.output_tokens '
                    'FROM runs r JOIN projects p ON p.id=r.project_id WHERE r.id=?', (run,)).fetchone()
                if (row is None or row[1:3] != ('failed', 'plan') or row[3] not in _ERRORS
                        or row[4:] != (0, 0)
                        or db.execute('SELECT 1 FROM revision_attempts WHERE run_id=?', (run,)).fetchone()):
                    raise StorageRefundError('storage_refund_dispatch_not_excluded')
                events = [item[0] for item in db.execute(
                    'SELECT type FROM run_events WHERE run_id=? ORDER BY seq', (run,))]
                if events != ['squad.role_started', 'run.failed']:
                    raise StorageRefundError('storage_refund_dispatch_not_excluded')
                rows = db.execute('SELECT user_id,delta,reason FROM credit_entries WHERE run_id=?', (run,)).fetchall()
                charges = [entry for entry in rows if entry[1] < 0]
                if len(charges) != 1 or charges[0] != (row[0], -1, 'plan'):
                    raise StorageRefundError('storage_refund_charge_mismatch')
                compensation = [entry for entry in rows if entry[1] > 0]
                if compensation:
                    if compensation != [(row[0], 1, _REASON)] or len(rows) != 2:
                        raise StorageRefundError('storage_refund_compensation_mismatch')
                    duplicate += 1
                    continue
                if len(rows) != 1:
                    raise StorageRefundError('storage_refund_charge_mismatch')
                if db.execute('UPDATE users SET credits=credits+1 WHERE id=?', (row[0],)).rowcount != 1:
                    raise StorageRefundError('storage_refund_owner_unavailable')
                db.execute('INSERT INTO credit_entries '
                    '(user_id,delta,reason,run_id,input_tokens,output_tokens,created_at) VALUES (?,1,?,?,0,0,?)',
                    (row[0], _REASON, run, datetime.now(timezone.utc).isoformat()))
                refunded += 1
                total += 1
            if db.execute('PRAGMA foreign_key_check').fetchall():
                raise StorageRefundError('storage_refund_integrity_failed')
            db.execute('COMMIT')
        except BaseException:
            db.execute('ROLLBACK')
            raise
    return {'refunded_runs': refunded, 'credits_restored': total, 'already_refunded_runs': duplicate}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True, type=Path)
    parser.add_argument('--backup', required=True, type=Path)
    parser.add_argument('--run-id', required=True, action='append')
    args = parser.parse_args()
    try:
        backup_database(args.database, args.backup)
        result = refund_storage_failures(args.database, tuple(args.run_id))
    except (StorageRefundError, MigrationError, sqlite3.Error, OSError):
        parser.exit(2, 'storage_refund_failed\n')
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
