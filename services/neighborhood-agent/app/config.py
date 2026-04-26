from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mcp_sql_url: str = "http://localhost:8020"
    mcp_safety_url: str = "http://localhost:8022"
    mcp_amenity_url: str = "http://localhost:8023"
    mcp_entertainment_url: str = "http://localhost:8024"
    request_timeout_seconds: float = 4.0
    poi_limit_default: int = 20
    use_llm_sql_planner: bool = True
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    neighborhood_agent_sql_model: str = "gpt-4o"
    llm_request_timeout_seconds: float = 20.0


settings = Settings()
