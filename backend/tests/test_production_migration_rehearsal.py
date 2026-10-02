"""Private copy rehearsal preserves real fixture rows and leaves the source alone."""
import hashlib
import importlib.util
from pathlib import Path

import pytest

from app.migrations import migrate, verify
from test_revision_migrations import legacy


SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'rehearse_production_migration.py'
spec = importlib.util.spec_from_file_location('rehearse_production_migration', SCRIPT)
rehearsal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rehearsal)


def test_rehearsal_preserves_source_and_all_preexisting_rows(legacy, tmp_path):
    source, _ = legacy
    for version in range(1, 11):
        migrate(source, tmp_path / f'prepare-v{version}.db', target_version=version)
    assert verify(source) == 10
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    scratch = tmp_path / 'private-scratch'
    scratch.mkdir(mode=0o700)

    result = rehearsal.rehearse(source, scratch)

    assert result['stages'] == [11, 12, 13, 14, 15]
    assert result['final_version'] == verify(scratch / 'atom.db') == 15
    assert result['preserved_tables'] > 10
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash
    assert all((scratch / f'before-v{version}.db').is_file() for version in range(11, 16))


def test_rehearsal_refuses_nonempty_scratch(legacy, tmp_path):
    source, _ = legacy
    scratch = tmp_path / 'private-scratch'
    scratch.mkdir(mode=0o700)
    (scratch / 'sentinel').write_text('preserve')
    with pytest.raises(RuntimeError, match='scratch_must_be_private_and_empty'):
        rehearsal.rehearse(source, scratch)
    assert (scratch / 'sentinel').read_text() == 'preserve'
