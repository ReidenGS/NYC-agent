import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mcp_amenity_url: str = "http://localhost:8028"
    mcp_entertainment_url: str = "http://localhost:8029"
    mcp_housing_url: str = "http://localhost:8021"
    mcp_safety_url: str = "http://localhost:8024"
    request_timeout_seconds: float = 4.0
    use_llm_sql_planner: bool = True
    openai_api_key: str = os.environ.get("OPENAI_API_KEY", "")
    openai_base_url: str = "https://api.openai.com/v1"
    nl_to_sql_agent_model: str = "gpt-4o"
    llm_request_timeout_seconds: float = 20.0
    skill_root: str = os.environ.get("NL_TO_SQL_SKILL_ROOT", "/app/skills/nyc-nl-to-sql")


settings = Settings()
