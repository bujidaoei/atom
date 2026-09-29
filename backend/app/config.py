from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process configuration. Every key is overridable via an ``ATOM_`` env var."""

    model_config = SettingsConfigDict(env_prefix="ATOM_", env_file=".env", extra="ignore")

    # --- security -------------------------------------------------------
    secret: str = "dev-secret-change-me"
    cookie_secure: bool = False
    cookie_path: str = "/"
    session_days: int = 14

    # --- storage --------------------------------------------------------
    data_dir: Path = Path("./data")
    db_path: Path = Path("./data/atom.db")

    # --- model gateway --------------------------------------------------
    llm_base_url: str = "https://ai-gateway.skg.com/v1"
    llm_api_key: str = ""

    # Budget for one model call inside the agent loop.
    llm_timeout_seconds: int = 300
    # Budget for a whole agent turn. A build turn writes several files and
    # runs shell verification, so it legitimately outlives many model calls.
    run_timeout_seconds: int = 1800
    # Wall-clock cap on a build turn. Agents will keep polishing forever if
    # allowed to; past this point the run is stopped and whatever is on disk
    # is what ships. The user can always ask for more in the next message.
    build_budget_seconds: int = 480

    # The gateway closes a response that stays open for roughly 60 seconds,
    # so throughput matters more than raw capability: a slow model gets cut
    # off mid-file no matter how good its code would have been. Both tiers
    # default to the fastest model that still writes decent code, and the
    # engineer prompt tells Alex to write in several small calls.
    llm_model: str = "deepseek-v4.1-flash"
    llm_planning_model: str = "deepseek-v4.1-flash"

    # --- agent runtime sidecar -----------------------------------------
    runtime_url: str = "http://127.0.0.1:8721"
    runtime_token: str = ""

    # --- quotas ---------------------------------------------------------
    starting_credits: int = 200
    race_max_models: int = 4

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
