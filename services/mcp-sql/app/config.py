from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url_sql: str = "postgresql+psycopg://nyc_agent:nyc_agent_password@localhost:5432/nyc_agent"
    sql_statement_timeout_ms: int = 3000
    sql_max_rows_default: int = 50

    @property
    def sqlalchemy_database_url(self) -> str:
        # Host .env may use asyncpg for FastAPI services. mcp-sql uses psycopg sync execution.
        return (
            self.database_url_sql
            .replace("postgresql+asyncpg://", "postgresql+psycopg://")
            .replace("postgres://", "postgresql+psycopg://")
        )


settings = Settings()
