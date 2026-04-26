from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mcp_profile_url: str = "http://localhost:8026"
    request_timeout_seconds: float = 3.0


settings = Settings()
