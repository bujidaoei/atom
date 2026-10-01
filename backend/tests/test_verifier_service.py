"""Fail-closed verifier process configuration without a Docker daemon."""
from pathlib import Path

import pytest

from app.verifier_service import VerifierProcessConfig, VerifierStartupError


def _config(tmp_path, **changes):
    values = dict(database=tmp_path / 'ledger.db', artifacts=tmp_path / 'artifacts',
                  image='sha256:' + 'a' * 64, seccomp=tmp_path / 'policy.json',
                  verifier_id='worker-1', control_token='x' * 48)
    return VerifierProcessConfig(**(values | changes))


def test_configuration_requires_absolute_pinned_private_inputs(tmp_path):
    assert _config(tmp_path).verifier_id == 'worker-1'
    for changes in ({'database':Path('relative.db')},
                    {'artifacts':Path('relative')},
                    {'seccomp':Path('relative.json')},
                    {'image':'latest'}, {'verifier_id':'bad name'},
                    {'control_token':'short'}, {'control_token':'x' * 40 + '\n'}):
        with pytest.raises(VerifierStartupError, match='verifier_configuration_invalid'):
            _config(tmp_path, **changes)


def test_control_credential_stays_out_of_configuration_repr(tmp_path, monkeypatch):
    config = _config(tmp_path)
    assert config.control_token not in repr(config)
    for name in ('ATOM_VERIFIER_DB_PATH', 'ATOM_VERIFIER_ARTIFACT_DIR',
                 'ATOM_VERIFIER_IMAGE', 'ATOM_VERIFIER_SECCOMP_PATH',
                 'ATOM_VERIFIER_ID', 'ATOM_VERIFIER_CONTROL_TOKEN'):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(VerifierStartupError, match='verifier_configuration_missing'):
        VerifierProcessConfig.from_environment()
