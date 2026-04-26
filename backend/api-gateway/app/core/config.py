from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

    app_name: str = 'NYC Agent API Gateway'
    debug: bool = True
    cors_origins: str = 'http://localhost:5173,http://127.0.0.1:5173'
    data_sync_base_url: str = 'http://localhost:8030'
    orchestrator_agent_url: str = 'http://localhost:8010'
    use_remote_orchestrator: bool = True
    agent_request_timeout_seconds: float = 4.0

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(',') if item.strip()]


settings = Settings()
