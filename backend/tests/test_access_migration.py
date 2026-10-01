import sqlite3

import pytest

from app.migrations import MigrationError, migrate, verify, verify_backup
from test_content_repository import content, release, ledger, legacy


@pytest.mark.parametrize('source_version',[0,1,2,3])
def test_access_upgrade_backup_restore_and_replay(legacy,tmp_path,source_version):
    path,baseline=legacy
    if source_version:migrate(path,baseline,target_version=source_version)
    backup=tmp_path/'before-access.db'
    result=migrate(path,backup,target_version=4)
    assert result.version==4 and verify(path)==4
    assert verify_backup(backup,expected_version=source_version)==result.backup_sha256
    assert not migrate(path,backup,target_version=4).applied
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT version FROM atom_schema_migrations ORDER BY version').fetchall()==[(1,),(2,),(3,),(4,)]
        for table in ('console_sessions','content_bootstraps','content_handoffs','content_sessions'):
            assert db.execute(f'SELECT count(*) FROM {table}').fetchone()==(0,)
        assert db.execute('SELECT prompt FROM projects').fetchone()==('actual preserved input',)
    restored=tmp_path/'restored.db'
    with sqlite3.connect(backup) as source,sqlite3.connect(restored) as target:source.backup(target)
    assert verify(restored)==source_version
    with pytest.raises(MigrationError,match='migration_downgrade_denied'):
        migrate(path,tmp_path/'downgrade.db',target_version=3)


def test_access_ddl_failure_preserves_v3(content,tmp_path,monkeypatch):
    from app.migrations import access_v4
    path,*_=content
    original=access_v4.apply
    def fail(db):
        original(db)
        raise sqlite3.OperationalError('injected migration failure')
    monkeypatch.setattr(access_v4,'apply',fail)
    backup=tmp_path/'before-failure.db'
    with pytest.raises(MigrationError):migrate(path,backup,target_version=4)
    assert verify(path)==3 and verify_backup(backup,expected_version=3)


@pytest.fixture
def access(content,tmp_path):
    path,repository,*_=content
    binding=repository.bind(owner='user',project_id='project',release_id='release')
    migrate(path,tmp_path/'before-access.db',target_version=4)
    db=sqlite3.connect(path)
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('INSERT INTO console_sessions VALUES (?,?,?,?,NULL)',('a'*32,'user',1,1000))
    db.execute('INSERT INTO content_bootstraps VALUES (?,?,?,?,NULL)',('b'*64,binding.id,10,130))
    try:yield db,binding.id
    finally:db.rollback();db.close()


def handoff(db,binding_id,**changes):
    values=dict(token='c'*64,bootstrap='b'*64,binding=binding_id,viewer='user',source='a'*32,generation=1,created=20,expires=100)
    values.update(changes)
    db.execute('INSERT INTO content_handoffs VALUES (?,?,?,?,?,?,?,?,NULL)',tuple(values.values()))


def session(db,binding_id,**changes):
    values=dict(token='d'*64,handoff='c'*64,binding=binding_id,viewer='user',source='a'*32,generation=1,created=30,expires=900)
    values.update(changes)
    db.execute('INSERT INTO content_sessions VALUES (?,?,?,?,?,?,?,?,NULL)',tuple(values.values()))


@pytest.mark.parametrize('changes',[{'token':'C'*64},{'viewer':'other'},{'source':'f'*32},
    {'binding':'f'*32},{'generation':0},{'created':9},{'expires':131},{'expires':20}])
def test_handoff_scope_source_and_expiry_constraints(access,changes):
    db,binding=access
    with pytest.raises(sqlite3.IntegrityError):handoff(db,binding,**changes)


def test_revoked_source_and_consumed_bootstrap_deny_handoff(access):
    db,binding=access
    db.execute('UPDATE console_sessions SET revoked_at=20')
    with pytest.raises(sqlite3.IntegrityError):handoff(db,binding)
    with pytest.raises(sqlite3.IntegrityError):db.execute('UPDATE console_sessions SET revoked_at=NULL')
    with pytest.raises(sqlite3.IntegrityError):db.execute('UPDATE console_sessions SET expires_at=2000')


def test_bootstrap_cannot_be_reused_or_extended(access):
    db,binding=access
    db.execute('UPDATE content_bootstraps SET consumed_at=20')
    with pytest.raises(sqlite3.IntegrityError):handoff(db,binding)
    with pytest.raises(sqlite3.IntegrityError):db.execute('UPDATE content_bootstraps SET consumed_at=NULL')
    with pytest.raises(sqlite3.IntegrityError):db.execute('UPDATE content_bootstraps SET expires_at=140')


@pytest.mark.parametrize('changes',[{'token':'D'*64},{'binding':'f'*32},{'viewer':'other'},
    {'source':'f'*32},{'generation':2},{'created':31},{'expires':1001},{'expires':30}])
def test_session_scope_redemption_and_expiry_constraints(access,changes):
    db,binding=access
    handoff(db,binding)
    db.execute('UPDATE content_bootstraps SET consumed_at=30')
    db.execute('UPDATE content_handoffs SET consumed_at=30')
    with pytest.raises(sqlite3.IntegrityError):session(db,binding,**changes)


def test_single_consumption_session_and_revocation(access):
    db,binding=access
    handoff(db,binding)
    with pytest.raises(sqlite3.IntegrityError):session(db,binding)
    db.execute('UPDATE content_handoffs SET consumed_at=30')
    with pytest.raises(sqlite3.IntegrityError):session(db,binding)
    db.execute('UPDATE content_bootstraps SET consumed_at=30')
    session(db,binding)
    with pytest.raises(sqlite3.IntegrityError):session(db,binding,token='e'*64)
    with pytest.raises(sqlite3.IntegrityError):db.execute('UPDATE content_handoffs SET consumed_at=31')
    with pytest.raises(sqlite3.IntegrityError):db.execute('UPDATE content_sessions SET publication_generation=2')
    db.execute('UPDATE content_sessions SET revoked_at=40')
    with pytest.raises(sqlite3.IntegrityError):db.execute('UPDATE content_sessions SET revoked_at=NULL')
    assert not db.execute('PRAGMA foreign_key_check').fetchall()


def test_expiry_boundary_and_revocation_before_exchange(access):
    db,binding=access
    handoff(db,binding)
    with pytest.raises(sqlite3.IntegrityError):db.execute('UPDATE content_handoffs SET consumed_at=100')
    with pytest.raises(sqlite3.IntegrityError):db.execute('UPDATE content_bootstraps SET consumed_at=130')
    db.execute('UPDATE content_handoffs SET consumed_at=30')
    db.execute('UPDATE content_bootstraps SET consumed_at=30')
    db.execute('UPDATE console_sessions SET revoked_at=30')
    with pytest.raises(sqlite3.IntegrityError):session(db,binding)


def test_session_cannot_outlive_source_even_within_own_limit(access):
    db,binding=access
    db.execute('INSERT INTO console_sessions VALUES (?,?,?,?,NULL)',('f'*32,'user',1,100))
    handoff(db,binding,source='f'*32)
    db.execute('UPDATE content_handoffs SET consumed_at=30')
    db.execute('UPDATE content_bootstraps SET consumed_at=30')
    with pytest.raises(sqlite3.IntegrityError):session(db,binding,source='f'*32,expires=101)
    session(db,binding,source='f'*32,expires=100)
