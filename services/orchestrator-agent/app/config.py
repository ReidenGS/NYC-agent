from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    profile_agent_url: str = "http://localhost:8014"
    request_timeout_seconds: float = 4.0


settings = Settings()
