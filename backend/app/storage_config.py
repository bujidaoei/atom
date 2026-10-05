"""Shared storage configuration without console or runtime credentials."""
from __future__ import annotations
from pathlib import Path
import re
from typing import Literal
from urllib.parse import urlsplit
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ObjectStorageSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='ATOM_', env_file='.env',
        extra='ignore', hide_input_in_errors=True)
    storage_backend: Literal['local', 'cos'] = 'local'
    upload_dir: Path | None = None
    storage_s3_endpoint: str = ''
    storage_s3_access_key: SecretStr = Field(default=SecretStr(''), repr=False, exclude=True)
    storage_s3_secret_key: SecretStr = Field(default=SecretStr(''), repr=False, exclude=True)
    storage_s3_bucket: str = ''
    storage_s3_region: str = ''
    storage_s3_prefix: str = ''
    storage_public_url_base: str = ''

    @model_validator(mode='after')
    def validate_object_storage(self) -> ObjectStorageSettings:
        if self.storage_backend == 'cos':
            region = self.storage_s3_region
            if re.fullmatch(r'[a-z]{2}-[a-z0-9-]+', region) is None:
                raise ValueError('invalid_cos_region')
            endpoint = urlsplit(self.storage_s3_endpoint)
            if (endpoint.scheme != 'https' or endpoint.netloc != f'cos.{region}.myqcloud.com'
                    or endpoint.path not in ('', '/') or endpoint.query or endpoint.fragment):
                raise ValueError('invalid_cos_endpoint')
            if re.fullmatch(r'[a-z0-9][a-z0-9-]{1,49}-[0-9]+', self.storage_s3_bucket) is None:
                raise ValueError('invalid_cos_bucket')
            if (not self.storage_s3_access_key.get_secret_value()
                    or not self.storage_s3_secret_key.get_secret_value()):
                raise ValueError('cos_credentials_required')
            if (not 1 <= len(self.storage_s3_prefix) <= 160
                    or any(re.fullmatch(r'[A-Za-z0-9_-]+', part) is None
                           for part in self.storage_s3_prefix.split('/'))):
                raise ValueError('invalid_cos_prefix')
        if self.storage_public_url_base:
            origin = urlsplit(self.storage_public_url_base)
            if (origin.scheme != 'https' or not origin.hostname or origin.username
                    or origin.password or origin.query or origin.fragment
                    or origin.path not in ('', '/')):
                raise ValueError('invalid_storage_public_origin')
        return self
