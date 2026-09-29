from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    secret: str = "dev-only-change-me"
    db_path: str = "data/atom.db"
    llm_base_url: str = "https://ai-gateway.skg.com/v1"
    llm_api_key: str = ""
    llm_model: str = "qwen3.7-plus"
    cookie_secure: bool = False
    daily_call_limit: int = 40

    model_config = SettingsConfigDict(env_prefix="ATOM_", env_file=".env", extra="ignore")


settings = Settings()

CURATED_MODELS = [
    {"id": "qwen3.7-plus", "label": "Qwen 3.7 Plus · 默认，能在网关时限内返回"},
    {"id": "claude-haiku-4-5", "label": "Claude Haiku 4.5 · 短回复快，长页面可能超时"},
    {"id": "claude-sonnet-5", "label": "Claude Sonnet 5 · 更慢"},
    {"id": "deepseek-v4-flash", "label": "DeepSeek V4 Flash · 思考更久"},
]
