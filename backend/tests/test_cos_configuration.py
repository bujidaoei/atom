"""Configuration validation uses synthetic credentials, never real bucket access."""
import json

import pytest
from pydantic import ValidationError

from app.config import Settings


def configuration(**overrides):
    return Settings(_env_file=None, **dict({
        'storage_backend': 'cos',
        'storage_s3_endpoint': 'https://cos.ap-guangzhou.myqcloud.com',
        'storage_s3_region': 'ap-guangzhou',
        'storage_s3_bucket': 'test-artifacts-1234567890',
        'storage_s3_prefix': 'test/atom',
        'storage_s3_access_key': 'synthetic-access-value',
        'storage_s3_secret_key': 'synthetic-secret-value',
    }, **overrides))


def test_cos_secrets_excluded_from_diagnostics_and_public_url_optional():
    settings = configuration()
    assert settings.storage_public_url_base == ''
    assert settings.storage_s3_secret_key.get_secret_value() == 'synthetic-secret-value'
    for encoded in (repr(settings), settings.model_dump_json(), json.dumps(settings.model_dump(), default=str)):
        assert 'synthetic-secret-value' not in encoded
        assert 'synthetic-access-value' not in encoded


@pytest.mark.parametrize('changes', [
    {'storage_s3_endpoint': 'http://cos.ap-guangzhou.myqcloud.com'},
    {'storage_s3_endpoint': 'https://cos.ap-guangzhou.myqcloud.com.evil.invalid'},
    {'storage_s3_endpoint': 'https://cos.ap-beijing.myqcloud.com'},
    {'storage_s3_endpoint': 'https://cos.ap-guangzhou.myqcloud.com/?redirect=1'},
    {'storage_s3_prefix': '../other-app'}, {'storage_s3_prefix': ''},
    {'storage_s3_prefix': 'test//atom'}, {'storage_s3_bucket': '../bucket'},
    {'storage_s3_access_key': ''}, {'storage_s3_secret_key': ''},
    {'storage_public_url_base': 'https://user:password@content.example.org'},
    {'storage_public_url_base': 'http://content.example.org'},
])
def test_cos_invalid_configuration_rejected_without_secret_disclosure(changes):
    with pytest.raises(ValidationError) as failure:
        configuration(**changes)
    assert 'synthetic-secret-value' not in str(failure.value)
    assert 'synthetic-access-value' not in str(failure.value)
