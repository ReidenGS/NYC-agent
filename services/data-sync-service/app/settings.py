from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://nyc_agent:nyc_agent_dev@localhost:5432/nyc_agent"

    sync_enable_scheduled_jobs: bool = False
    sync_bootstrap_areas: str = (
        "Astoria,Long Island City,Williamsburg,Greenpoint,Midtown,"
        "East Village,Upper West Side,Sunnyside,Bushwick,Downtown Brooklyn"
    )

    socrata_app_token: str = ""
    socrata_page_size: int = 1000
    socrata_max_rows_per_job: int = 50_000

    rentcast_sync_enabled: bool = False
    rentcast_api_key: str = ""
    rentcast_max_calls_per_run: int = 5
    rentcast_max_calls_per_month: int = 50

    overpass_max_requests_per_run: int = 10
    overpass_sleep_seconds: int = 3

    map_layer_pregenerate_for_seed: bool = True

    @property
    def bootstrap_area_list(self) -> list[str]:
        return [a.strip() for a in self.sync_bootstrap_areas.split(",") if a.strip()]


settings = Settings()
