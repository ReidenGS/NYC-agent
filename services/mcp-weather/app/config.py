from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    nws_user_agent: str = "NYC-agent-demo/0.1 (contact@example.com)"
    request_timeout_seconds: float = 4.0


settings = Settings()
