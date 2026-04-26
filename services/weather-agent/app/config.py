from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mcp_weather_url: str = "http://localhost:8027"
    request_timeout_seconds: float = 4.0


settings = Settings()
