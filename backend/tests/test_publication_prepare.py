"""The deployment preparation CLI must preserve its source and fail closed."""
import hashlib
import shutil

import pytest

from app.migrations import migrate, verify
from app.project_origins import ProjectOriginRepository
from app.publication_prepare import PreparationError, prepare
from test_revision_migrations import legacy


def test_prepare_real_schema_chain_and_origin_pair_on_disposable_copy(legacy, tmp_path):
    source, _ = legacy
    migrate(source, tmp_path / 'baseline-v10.db', target_version=10)
    original = hashlib.sha256(source.read_bytes()).hexdigest()
    candidate = tmp_path / 'candidate.db'
    shutil.copyfile(source, candidate)
    backups = tmp_path / 'candidate-predecessors'

    result = prepare(candidate, backups, source_sha256=original,
                     expected_counts={'projects': 1, 'revision_records': 0,
                                      'revision_artifacts': 0},
                     first_port=20000, last_port=20003)

    assert result['schema'] == verify(candidate) == 18
    assert result['predecessorVersions'] == list(range(11, 19))
    assert result['originPairs'] == 1
    assert result['lastAllocatedPort'] == 20001
    assert ProjectOriginRepository(candidate, first_port=20000,
                                   last_port=20003).for_project('project').public_port == 20001
    assert len(list(backups.iterdir())) == 8
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original


def test_prepare_rejects_changed_source_before_creating_backups(legacy, tmp_path):
    source, _ = legacy
    migrate(source, tmp_path / 'baseline-v10.db', target_version=10)
    backups = tmp_path / 'candidate-predecessors'

    with pytest.raises(PreparationError, match='source_digest_changed'):
        prepare(source, backups, source_sha256='0' * 64,
                expected_counts={'projects': 1, 'revision_records': 0,
                                 'revision_artifacts': 0},
                first_port=20000, last_port=20003)

    assert verify(source) == 10
    assert not backups.exists()


def test_prepare_refuses_insufficient_origin_capacity_before_migration(legacy, tmp_path):
    source, _ = legacy
    migrate(source, tmp_path / 'baseline-v10.db', target_version=10)
    backups = tmp_path / 'candidate-predecessors'
    digest = hashlib.sha256(source.read_bytes()).hexdigest()

    with pytest.raises(PreparationError, match='origin_capacity'):
        prepare(source, backups, source_sha256=digest,
                expected_counts={'projects': 2, 'revision_records': 0,
                                 'revision_artifacts': 0},
                first_port=20000, last_port=20001)

    assert verify(source) == 10
    assert not backups.exists()
