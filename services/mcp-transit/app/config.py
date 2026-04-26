from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url_sync: str = "postgresql+psycopg://nyc_agent:nyc_agent_password@localhost:5432/nyc_agent"
    transit_statement_timeout_ms: int = 3000
    transit_realtime_enabled: bool = True
    transit_realtime_ttl_seconds: int = 60
    transit_realtime_request_timeout_seconds: float = 5.0
    mta_api_key: str = ""
    mta_bus_time_api_key: str = ""
    mta_subway_feed_base_url: str = "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2F"
    mta_bus_gtfs_rt_trip_updates_url: str = "https://gtfsrt.prod.obanyc.com/tripUpdates"

    @property
    def sqlalchemy_database_url(self) -> str:
        return (
            self.database_url_sync
            .replace("postgresql+asyncpg://", "postgresql+psycopg://")
            .replace("postgres://", "postgresql+psycopg://")
        )


settings = Settings()
