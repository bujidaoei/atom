from __future__ import annotations

from functools import lru_cache
from ipaddress import ip_address
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


from .storage_config import ObjectStorageSettings


class Settings(ObjectStorageSettings):
    """Process configuration. Every key is overridable via an ``ATOM_`` env var."""

    model_config = SettingsConfigDict(
        env_prefix="ATOM_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )

    # --- security -------------------------------------------------------
    environment: Literal["development", "test", "production"] = "development"
    secret: str = Field(repr=False)
    session_mode: Literal["legacy", "durable"] = "legacy"
    console_proof_required: bool = False
    console_origin: str | None = None
    content_host_suffix: str | None = None
    ip_preview_enabled: bool = False
    ip_public_enabled: bool = False
    ip_preview_address: str | None = None
    ip_preview_first_port: int | None = None
    ip_preview_last_port: int | None = None
    ip_ingress_ca_file: Path | None = None
    publication_verification: Literal['advisory', 'required'] = 'advisory'
    cookie_secure: bool = False
    cookie_path: str = "/"
    session_days: int = Field(default=14, ge=1, le=90)
    audit_export_config: str = Field(default='[]', repr=False, exclude=True)
    audit_export_interval_seconds: int = Field(default=5, ge=1, le=300)
    audit_export_ca_file: Path | None = None

    # --- storage --------------------------------------------------------
    data_dir: Path = Path("./data")
    db_path: Path = Path("./data/atom.db")
    # --- model gateway --------------------------------------------------
    llm_base_url: str = "https://ai-gateway.skg.com/v1"
    llm_api_key: str = Field(default="", repr=False)

    # Budget for one model call inside the agent loop.
    llm_timeout_seconds: int = Field(default=300, ge=1, le=1800)
    # Budget for a whole agent turn. A build turn writes several files and
    # runs shell verification, so it legitimately outlives many model calls.
    run_timeout_seconds: int = Field(default=1800, ge=1, le=7200)
    # Hard elapsed-time cap, including silent transport and recovery.
    # Timeout preserves files but is never successful completion.
    build_budget_seconds: int = Field(default=180, ge=1, le=1800)

    # The gateway closes a response that stays open for roughly 60 seconds,
    # so throughput matters more than raw capability: a slow model gets cut
    # off mid-file no matter how good its code would have been. Both tiers
    # default to the fastest model that still writes decent code, and the
    # engineer prompt tells Alex to write in several small calls.
    llm_model: str = "deepseek-v4.1-flash"
    llm_planning_model: str = "deepseek-v4.1-flash"

    # --- agent runtime sidecar -----------------------------------------
    runtime_url: str = "http://127.0.0.1:8721"
    runtime_token: str = Field(repr=False)
    sandbox_mode: Literal['local', 'broker'] | None = None
    broker_origin: str | None = None
    artifact_dir: Path | None = None
    broker_admin_token: str | None = Field(default=None, repr=False)
    broker_grant_key: str | None = Field(default=None, repr=False)
    completion_grant_key: str | None = Field(default=None, repr=False)
    verifier_origin: str | None = None
    verifier_control_token: str | None = Field(default=None, repr=False)
    verifier_policy_digest: str | None = None
    verifier_runner_version: str | None = None
    verifier_budget_seconds: int = Field(default=90, ge=45, le=300)

    # --- quotas ---------------------------------------------------------
    starting_credits: int = Field(default=200, ge=0, le=1_000_000)
    race_max_models: int = Field(default=4, ge=1, le=16)

    @field_validator("secret", "runtime_token")
    @classmethod
    def validate_service_secret(cls, value: str) -> str:
        if (len(value) < 32 or len(value) > 512
                or any(not 33 <= ord(c) <= 126 for c in value)
                or any(marker in value.lower() for marker in ("change-me", "dev-secret"))):
            raise ValueError("requires an independently generated secret of 32–512 printable nonspace ASCII characters")
        return value

    @field_validator("cookie_path")
    @classmethod
    def validate_cookie_path(cls, value: str) -> str:
        if not value.startswith("/") or any(ord(c) < 32 or c in ";\\" for c in value):
            raise ValueError("cookie_path must be an absolute cookie path")
        return value

    @model_validator(mode="after")
    def validate_transport(self) -> Settings:
        destinations = self.audit_destinations
        if destinations and self.session_mode != 'durable':
            raise ValueError('audit_export_requires_durable_sessions')
        if self.audit_export_ca_file is not None and not self.audit_export_ca_file.is_absolute():
            raise ValueError('audit_export_requires_absolute_ca_file')
        if any(item.token in (self.secret, self.runtime_token, self.llm_api_key,
                self.broker_admin_token, self.broker_grant_key, self.completion_grant_key) for item in destinations):
            raise ValueError('audit_export_requires_independent_credentials')
        if self.session_mode == 'durable':
            from .content_bootstrap import ContentNavigation
            ContentNavigation(self.console_origin)
            if not self.cookie_secure or self.cookie_path != '/':
                raise ValueError('durable sessions require secure root cookies')
        elif self.console_proof_required:
            raise ValueError('console proof requires durable sessions')
        if self.content_host_suffix is not None:
            from .content_hosts import ContentHosts
            from .content_bootstrap import ContentNavigation
            if self.session_mode != 'durable':
                raise ValueError('content handoff requires durable sessions')
            ContentNavigation(self.console_origin).validate_content_hosts(ContentHosts(self.content_host_suffix))
        if self.ip_preview_enabled:
            if (self.session_mode != 'durable' or not self.console_proof_required
                    or self.verifier_origin is None
                    or self.ip_preview_address is None
                    or self.ip_preview_first_port is None or self.ip_preview_last_port is None):
                raise ValueError('ip preview requires durable console proof, verifier and complete origin configuration')
            if (self.ip_ingress_ca_file is not None and
                    (not self.ip_ingress_ca_file.is_absolute()
                     or not self.ip_ingress_ca_file.is_file())):
                raise ValueError('ip ingress CA file must be an absolute readable file')
            # Validate the literal address without touching the database here.
            try:
                parsed = ip_address(self.ip_preview_address.strip('[]'))
                canonical = f'[{parsed.compressed}]' if parsed.version == 6 else parsed.compressed
                if canonical != self.ip_preview_address:
                    raise ValueError
            except ValueError:
                raise ValueError('ip preview requires a canonical literal address') from None
            if (type(self.ip_preview_first_port) is not int or type(self.ip_preview_last_port) is not int
                    or not 1024 <= self.ip_preview_first_port < self.ip_preview_last_port <= 65535
                    or self.ip_preview_last_port - self.ip_preview_first_port + 1 > 512):
                raise ValueError('invalid ip preview port range')
            if self.console_origin != f'https://{canonical}':
                raise ValueError('ip preview must use the console IP address')
        if self.ip_public_enabled and not self.ip_preview_enabled:
            raise ValueError('ip public delivery requires isolated preview and console proof')
        self.sandbox_mode = self.sandbox_mode or ('broker' if self.environment == 'production' else 'local')
        if self.environment == 'production' and self.sandbox_mode != 'broker':
            raise ValueError('production requires broker execution')
        if self.sandbox_mode == 'broker':
            if self.run_timeout_seconds > 7140:
                raise ValueError('broker run timeout must leave 60 seconds within the 7200-second lease limit')
            from .sandbox.client import _origin, BrokerClientError
            try:
                self.broker_origin = _origin(self.broker_origin)
            except BrokerClientError:
                raise ValueError('invalid broker origin') from None
            if self.artifact_dir is None or not self.artifact_dir.is_absolute():
                raise ValueError('broker execution requires an absolute artifact directory')
            values = (self.broker_admin_token, self.broker_grant_key, self.completion_grant_key)
            if any(not isinstance(value, str) or not 32 <= len(value) <= 128
                   or any(not 33 <= ord(c) <= 126 for c in value)
                   or any(marker in value.lower() for marker in ('change-me', 'dev-secret')) for value in values):
                raise ValueError('broker execution requires independent 32–128 character secrets')
            if len(set(values)) != 3 or any(value in (self.secret, self.runtime_token, self.llm_api_key) for value in values):
                raise ValueError('execution secrets must be distinct from other service credentials')
        verifier_values = (self.verifier_origin, self.verifier_control_token,
                           self.verifier_policy_digest, self.verifier_runner_version)
        if any(value is not None for value in verifier_values):
            from .verifier_client import _origin as verifier_origin, VerifierClientError
            import re
            if any(value is None for value in verifier_values) or self.sandbox_mode != 'broker':
                raise ValueError('verifier requires complete broker-mode configuration')
            try:
                self.verifier_origin = verifier_origin(self.verifier_origin)
            except VerifierClientError:
                raise ValueError('invalid verifier origin') from None
            token = self.verifier_control_token
            if (not 32 <= len(token) <= 256 or not token.isascii()
                    or any(not 33 <= ord(char) <= 126 for char in token)
                    or any(marker in token.lower() for marker in ('change-me', 'dev-secret'))
                    or token in (self.secret, self.runtime_token, self.llm_api_key,
                                 self.broker_admin_token, self.broker_grant_key,
                                 self.completion_grant_key)
                    or re.fullmatch(r'[0-9a-f]{64}', self.verifier_policy_digest) is None
                    or re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', self.verifier_runner_version) is None):
                raise ValueError('invalid verifier identity or independent credential')
        if self.secret == self.runtime_token:
            raise ValueError("session signing and runtime authentication require different secrets")
        try:
            target = urlsplit(self.runtime_url)
            if (target.scheme not in {"http", "https"} or not target.hostname
                    or target.username is not None or target.password is not None
                    or target.query or target.fragment or target.port == 0
                    or any(c.isspace() or c in "\\%?#" for c in self.runtime_url)):
                raise ValueError
            port = target.port
            if port is not None and not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            raise ValueError("runtime_url must be an absolute HTTP(S) service URL without credentials, query or fragment") from None
        if self.environment == "production":
            if not self.cookie_secure:
                raise ValueError("production requires cookie_secure=true and HTTPS at the console proxy")
            try:
                loopback = ip_address(target.hostname).is_loopback
            except ValueError:
                loopback = False
            if target.scheme != "https" and not loopback:
                raise ValueError("production runtime transport requires HTTPS or a literal loopback address")
        return self

    @property
    def audit_destinations(self):
        from .audit_configuration import audit_destinations
        return audit_destinations(self.audit_export_config)

    @property
    def projects_dir(self) -> Path:
        return self.data_dir / "projects"

    @property
    def published_dir(self) -> Path:
        return self.data_dir / "published"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    # Workspace paths cross a process boundary into the Node runtime, which
    # has its own working directory. Anything relative would resolve against
    # the wrong root there, so absolutise once, here.
    settings.data_dir = settings.data_dir.resolve()
    settings.db_path = settings.db_path.resolve()
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    settings.projects_dir.mkdir(parents=True, exist_ok=True)
    settings.published_dir.mkdir(parents=True, exist_ok=True)
    return settings
