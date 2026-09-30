"""Explicit standalone broker configuration; never load API secrets or dotenv."""
from dataclasses import dataclass, field
import os
from pathlib import Path
import re
from collections.abc import Mapping


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class BrokerConfig:
    registry_path: Path
    image: str
    admin_token: str = field(repr=False)
    grant_key: str = field(repr=False)
    sweep_seconds: int = 5
    batch_size: int = 100
    port: int = 8766

    def __post_init__(self):
        if not isinstance(self.registry_path, Path) or not self.registry_path.is_absolute():
            raise ConfigError("invalid_registry_path")
        if not isinstance(self.image, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", self.image):
            raise ConfigError("image_not_pinned")
        for value in (self.admin_token, self.grant_key):
            if (not isinstance(value, str) or not 32 <= len(value) <= 128
                    or any(not 33 <= ord(c) <= 126 for c in value)
                    or any(marker in value.lower() for marker in ("change-me", "dev-secret"))):
                raise ConfigError("invalid_broker_secret")
        if self.admin_token == self.grant_key:
            raise ConfigError("broker_secrets_must_differ")
        for value, low, high in ((self.sweep_seconds, 1, 60), (self.batch_size, 1, 1000), (self.port, 1024, 65535)):
            if type(value) is not int or not low <= value <= high:
                raise ConfigError("invalid_broker_limit")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None):
        values = os.environ if env is None else env
        try:
            configured = cls(Path(values["ATOM_BROKER_REGISTRY_PATH"]), values["ATOM_BROKER_IMAGE"],
                       values["ATOM_BROKER_ADMIN_TOKEN"], values["ATOM_BROKER_GRANT_KEY"],
                       int(values.get("ATOM_BROKER_SWEEP_SECONDS", "5")),
                       int(values.get("ATOM_BROKER_BATCH_SIZE", "100")),
                       int(values.get("ATOM_BROKER_PORT", "8766")))
            if any(values.get(name) in (configured.admin_token, configured.grant_key)
                   for name in ("ATOM_SECRET", "ATOM_RUNTIME_TOKEN", "ATOM_LLM_API_KEY")):
                raise ConfigError("reused_service_secret")
            return configured
        except (KeyError, ValueError, TypeError):
            raise ConfigError("invalid_broker_configuration") from None
