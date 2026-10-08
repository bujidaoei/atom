import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.storage_refunds import refund_storage_failures, StorageRefundError
from test_adoption_repository import prepared
from test_revision_migrations import legacy

RUN = 'a' * 32


@pytest.fixture
def refundable(prepared):
    path = prepared[0]
    with sqlite3.connect(path) as db:
        db.execute('UPDATE runs SET id=?,status=?,phase=?,error=?,input_tokens=0,output_tokens=0 WHERE id=?',
            (RUN, 'failed', 'plan', 'artifact_io_error', 'run'))
        db.execute('UPDATE users SET credits=9 WHERE id=?', ('user',))
        db.execute("INSERT INTO credit_entries(user_id,delta,reason,run_id,input_tokens,output_tokens,created_at) "
            "VALUES ('user',-1,'plan',?,0,0,'2026-10-08')", (RUN,))
        for seq, kind in enumerate(('squad.role_started', 'run.failed'), 1):
            db.execute("INSERT INTO run_events(project_id,seq,run_id,type,payload_json,created_at) "
                "VALUES ('project',?,?,?,'{}','2026-10-08')", (seq, RUN, kind))
    return path


def test_atomic_compensation_is_idempotent_and_preserves_original_charge(refundable):
    assert refund_storage_failures(refundable, (RUN,)) == {
        'refunded_runs': 1, 'credits_restored': 1, 'already_refunded_runs': 0}
    assert refund_storage_failures(refundable, (RUN,)) == {
        'refunded_runs': 0, 'credits_restored': 0, 'already_refunded_runs': 1}
    with sqlite3.connect(refundable) as db:
        assert db.execute('SELECT credits FROM users WHERE id=?', ('user',)).fetchone() == (10,)
        assert db.execute('SELECT delta,reason FROM credit_entries ORDER BY id').fetchall() == [
            (-1, 'plan'), (1, 'storage_preparation_refund')]


@pytest.mark.parametrize('change', [
    "UPDATE runs SET input_tokens=1", "UPDATE runs SET phase='build'",
    "UPDATE runs SET error='model_error'", "UPDATE run_events SET type='run.started' WHERE seq=1",
    "UPDATE credit_entries SET delta=-2",
])
def test_uncertain_dispatch_or_charge_is_never_refunded(refundable, change):
    with sqlite3.connect(refundable) as db: db.execute(change)
    with pytest.raises(StorageRefundError): refund_storage_failures(refundable, (RUN,))
    with sqlite3.connect(refundable) as db:
        assert db.execute('SELECT credits FROM users WHERE id=?', ('user',)).fetchone() == (9,)
        assert db.execute('SELECT count(*) FROM credit_entries').fetchone() == (1,)


def test_later_invalid_run_rolls_back_earlier_compensation(refundable):
    with pytest.raises(StorageRefundError):
        refund_storage_failures(refundable, (RUN, 'b' * 32))
    with sqlite3.connect(refundable) as db:
        assert db.execute('SELECT credits FROM users WHERE id=?', ('user',)).fetchone() == (9,)


def test_concurrent_replays_restore_exactly_one_credit(refundable):
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: refund_storage_failures(refundable, (RUN,)), range(4)))
    assert sum(result['credits_restored'] for result in results) == 1
    with sqlite3.connect(refundable) as db:
        assert db.execute('SELECT credits FROM users WHERE id=?', ('user',)).fetchone() == (10,)
        assert db.execute('SELECT count(*) FROM credit_entries').fetchone() == (2,)


def test_registered_execution_attempt_prevents_guessing_from_zero_tokens(refundable):
    from app.revisions import RevisionRepository
    with sqlite3.connect(refundable) as db:
        workspace = db.execute('SELECT id FROM revision_workspaces WHERE heat_id IS NULL').fetchone()[0]
        db.execute("UPDATE runs SET status='running' WHERE id=?", (RUN,))
        db.execute("UPDATE projects SET active_run_id=? WHERE id='project'", (RUN,))
    RevisionRepository(refundable).reserve('user', workspace, RUN, 'attempt', 'grant', int(time.time()) + 90)
    with sqlite3.connect(refundable) as db:
        db.execute("UPDATE runs SET status='failed' WHERE id=?", (RUN,))
        db.execute("UPDATE projects SET active_run_id=NULL WHERE id='project'")
    with pytest.raises(StorageRefundError, match='storage_refund_dispatch_not_excluded'):
        refund_storage_failures(refundable, (RUN,))
