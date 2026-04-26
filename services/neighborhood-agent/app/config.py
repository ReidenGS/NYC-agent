from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mcp_sql_url: str = "http://localhost:8020"
    request_timeout_seconds: float = 4.0
    poi_limit_default: int = 20


settings = Settings()
