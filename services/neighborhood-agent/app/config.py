import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mcp_safety_url: str = "http://localhost:8024"
    mcp_amenity_url: str = "http://localhost:8028"
    mcp_entertainment_url: str = "http://localhost:8029"
    request_timeout_seconds: float = 4.0
    poi_limit_default: int = 20
    use_llm_sql_planner: bool = True
    openai_api_key: str = os.environ.get("OPENAI_API_KEY", "")
    openai_base_url: str = "https://api.openai.com/v1"
    neighborhood_agent_sql_model: str = "gpt-4o"
    llm_request_timeout_seconds: float = 20.0
    crime_category_rag_embedding_model: str = "text-embedding-3-small"
    crime_category_rag_top_k: int = 6
    crime_category_rag_min_similarity: float = 0.60
    crime_category_rag_min_margin: float = 0.02


settings = Settings()
