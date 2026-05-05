import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mcp_transit_url: str = "http://localhost:8025"
    request_timeout_seconds: float = 4.0
    openai_api_key: str = os.environ.get("OPENAI_API_KEY", "")
    openai_base_url: str = "https://api.openai.com/v1"
    transit_agent_tool_model: str = "gpt-4o"
    llm_request_timeout_seconds: float = 20.0

    # Transit endpoint RAG (stop_dimension + NTA fusion)
    database_url_sql: str = "postgresql+psycopg://nyc_agent:nyc_agent_password@localhost:5432/nyc_agent"
    transit_rag_embedding_model: str = "text-embedding-3-small"
    transit_rag_top_k: int = 5
    transit_rag_min_similarity: float = 0.78
    transit_rag_min_margin: float = 0.04


settings = Settings()
