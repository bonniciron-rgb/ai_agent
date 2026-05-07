from enum import StrEnum
from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class T212Env(StrEnum):
    demo = "demo"
    live = "live"


class RunMode(StrEnum):
    dry_run = "dry_run"
    paper = "paper"
    live = "live"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    anthropic_api_key: SecretStr = Field(default=SecretStr(""))

    t212_api_key: SecretStr = Field(default=SecretStr(""))
    t212_env: T212Env = T212Env.demo

    telegram_bot_token: SecretStr = Field(default=SecretStr(""))
    telegram_chat_id: str = ""

    # Telegram MTProto credentials for reading external signal channels.
    # Obtain from https://my.telegram.org; session string from scripts/auth_telegram.py
    telegram_api_id: int | None = None
    telegram_api_hash: SecretStr = Field(default=SecretStr(""))
    telegram_session_string: SecretStr = Field(default=SecretStr(""))

    finnhub_api_key: SecretStr = Field(default=SecretStr(""))
    fred_api_key: SecretStr = Field(default=SecretStr(""))
    newsapi_key: SecretStr = Field(default=SecretStr(""))
    edgar_user_agent: str = "ai_agent/0.1 (set-real-contact@example.com)"

    database_url: str = "sqlite+pysqlite:///:memory:"

    log_level: str = "INFO"
    llm_daily_cost_cap_usd: float = 3.0
    llm_daily_cost_alert_usd: float = 2.0
    run_mode: RunMode = RunMode.dry_run

    @property
    def t212_base_url(self) -> str:
        if self.t212_env is T212Env.live:
            return "https://live.trading212.com"
        return "https://demo.trading212.com"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
