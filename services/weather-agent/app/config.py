import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mcp_weather_url: str = "http://localhost:8027"
    request_timeout_seconds: float = 4.0
    openai_api_key: str = os.environ.get("OPENAI_API_KEY", "")
    openai_base_url: str = "https://api.openai.com/v1"
    weather_agent_tool_model: str = "gpt-4o"
    llm_request_timeout_seconds: float = 20.0


settings = Settings()
