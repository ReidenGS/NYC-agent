from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url_sync: str = "postgresql+psycopg://nyc_agent:nyc_agent_password@localhost:5432/nyc_agent"
    weather_statement_timeout_ms: int = 3000
    nws_user_agent: str = "NYC-agent-demo/0.1 (contact@example.com)"
    request_timeout_seconds: float = 4.0

    @property
    def sqlalchemy_database_url(self) -> str:
        return (
            self.database_url_sync
            .replace("postgresql+asyncpg://", "postgresql+psycopg://")
            .replace("postgres://", "postgresql+psycopg://")
        )


settings = Settings()
