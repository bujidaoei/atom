"""Generation policy capture is separate from private credential migration."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'deploy'))
import generation_settings


def test_capture_whitelist_and_configuration_precedence(tmp_path, monkeypatch):
    (tmp_path / '.env').write_text('private test fixture')
    monkeypatch.setattr(generation_settings, '_private_file', lambda path: {
        'ATOM_BUILD_BUDGET_SECONDS': '5400', 'ATOM_RUN_TIMEOUT_SECONDS': '5400',
        'ATOM_SECRET': 'must-not-be-forwarded', 'ATOM_LLM_API_KEY': 'must-not-be-forwarded'})
    result = generation_settings.capture(tmp_path, {
        'ATOM_BUILD_BUDGET_SECONDS': '180', 'ATOM_SECRET': 'existing-private'})
    assert result == {'ATOM_BUILD_BUDGET_SECONDS': '5400', 'ATOM_RUN_TIMEOUT_SECONDS': '5400'}
    assert generation_settings.capture(tmp_path / 'absent', {}) == {}


@pytest.mark.parametrize('values', [
    {'ATOM_BUILD_BUDGET_SECONDS': '0'}, {'ATOM_RUN_TIMEOUT_SECONDS': '7141'},
    {'ATOM_LLM_TIMEOUT_SECONDS': '300'}, {'ATOM_SECRET': 'never-echo'},
    {'ATOM_BUILD_BUDGET_SECONDS': 'nan'}, {'ATOM_BUILD_BUDGET_SECONDS': '3600\nsecret'},
])
def test_invalid_policy_is_rejected_without_values(values):
    with pytest.raises(generation_settings.EnvironmentError) as caught:
        generation_settings.validate(values)
    assert 'secret' not in str(caught.value)


def test_explicit_long_model_wait_and_lease_boundary():
    values = {'ATOM_BUILD_BUDGET_SECONDS': '7140', 'ATOM_RUN_TIMEOUT_SECONDS': '3600',
              'ATOM_LLM_TIMEOUT_SECONDS': '7140'}
    assert generation_settings.validate(values) == values


@pytest.mark.parametrize('value', ['0', '1', '2', '3'])
def test_repair_attempt_policy_is_captured(value):
    assert generation_settings.validate({'ATOM_GENERATION_REPAIR_ATTEMPTS': value}) == {'ATOM_GENERATION_REPAIR_ATTEMPTS': value}


@pytest.mark.parametrize('value', ['-1', '4', '1.5', 'secret'])
def test_repair_attempt_policy_rejects_invalid_values(value):
    with pytest.raises(generation_settings.EnvironmentError):
        generation_settings.validate({'ATOM_GENERATION_REPAIR_ATTEMPTS': value})
