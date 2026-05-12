import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "NYC Agent Orchestrator"

    # LLM
    openai_api_key: str = os.environ.get("OPENAI_API_KEY", "")
    openai_base_url: str = "https://api.openai.com/v1"
    orchestrator_understand_model: str = "gpt-4o-mini"
    orchestrator_respond_model: str = "gpt-4o-mini"
    llm_request_timeout_seconds: float = 20.0
    area_rag_embedding_model: str = "text-embedding-3-small"
    area_rag_top_k: int = 5
    area_rag_min_similarity: float = 0.78
    area_rag_min_margin: float = 0.04

    # LangGraph checkpointer (own connection, separate schema from business tables)
    database_url_async: str = (
        "postgresql://nyc_agent:nyc_agent_password@localhost:5432/nyc_agent"
    )
    langgraph_checkpoint_schema: str = "langgraph_checkpoints"

    # A2A downstream URLs
    neighborhood_agent_url: str = "http://localhost:8012"
    housing_agent_url: str = "http://localhost:8011"
    transit_agent_url: str = "http://localhost:8013"
    weather_agent_url: str = "http://localhost:8015"
    profile_agent_url: str = "http://localhost:8014"
    data_sync_base_url: str = "http://data-sync-service:8030"
    request_timeout_seconds: float = 30.0

    # LangSmith — silently no-op when LANGCHAIN_API_KEY missing
    langchain_tracing_v2: bool = False
    langchain_project: str = "nyc-agent"


settings = Settings()
