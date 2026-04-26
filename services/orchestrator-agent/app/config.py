from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    profile_agent_url: str = "http://localhost:8014"
    housing_agent_url: str = "http://localhost:8011"
    neighborhood_agent_url: str = "http://localhost:8012"
    transit_agent_url: str = "http://localhost:8013"
    weather_agent_url: str = "http://localhost:8015"
    request_timeout_seconds: float = 4.0


settings = Settings()
