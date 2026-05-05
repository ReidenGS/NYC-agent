import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mcp_profile_url: str = "http://localhost:8026"
    request_timeout_seconds: float = 3.0
    openai_api_key: str = os.environ.get("OPENAI_API_KEY", "")
    openai_base_url: str = "https://api.openai.com/v1"
    profile_agent_tool_model: str = "gpt-4o"
    llm_request_timeout_seconds: float = 20.0


settings = Settings()
