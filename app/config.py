from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    keitaro_url: str = ""
    keitaro_api_key: str = ""
    keitaro_fake: bool = False
    keitaro_timeout: float = 20.0
    keitaro_connect_timeout: float = 5.0
    keitaro_retries: int = 3          # дополнительных попыток после первой
    keitaro_backoff: float = 0.5      # пауза между попытками: 0.5, 1, 2 секунды
    log_level: str = "INFO"

    database_url: str = "sqlite:///./app.db"

    default_domain: str = ""
    default_group_name: str = "FORTESTS"
    default_source_name: str = "FORTESTS"
    safe_redirect_url: str = "https://google.com"


@lru_cache
def get_settings() -> Settings:
    return Settings()
