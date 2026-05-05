import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mcp_housing_url: str = "http://localhost:8021"
    request_timeout_seconds: float = 4.0
    listing_limit_default: int = 5
    listing_limit_max: int = 10
    use_llm_sql_planner: bool = True
    openai_api_key: str = os.environ.get("OPENAI_API_KEY", "")
    openai_base_url: str = "https://api.openai.com/v1"
    housing_agent_sql_model: str = "gpt-4o"
    llm_request_timeout_seconds: float = 20.0


settings = Settings()
