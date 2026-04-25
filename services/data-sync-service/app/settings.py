from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # data-sync-service is sync code (psycopg). It must NOT depend on the
    # asyncpg-flavoured DATABASE_URL. Resolution order:
    #   1. DATABASE_URL_SYNC_DOCKER  (set by docker-compose inside the network)
    #   2. DATABASE_URL_SYNC         (host-side override)
    #   3. DATABASE_URL              (legacy alias; only respected if it's
    #                                already a psycopg DSN — see _resolved_db_url)
    #   4. built-in psycopg default for local dev
    database_url_sync_docker: str = ""
    database_url_sync: str = ""
    database_url: str = ""

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

    hud_user_api_token: str = ""

    overpass_max_requests_per_run: int = 10
    overpass_sleep_seconds: int = 3

    map_layer_pregenerate_for_seed: bool = True

    zori_zip_csv_url: str = (
        "https://files.zillowstatic.com/research/public_csvs/zori/"
        "Zip_zori_uc_sfrcondomfr_sm_month.csv"
    )

    mta_bus_static_feed_urls: str = (
        "http://web.mta.info/developers/data/nyct/bus/google_transit_bronx.zip,"
        "http://web.mta.info/developers/data/nyct/bus/google_transit_brooklyn.zip,"
        "http://web.mta.info/developers/data/nyct/bus/google_transit_manhattan.zip,"
        "http://web.mta.info/developers/data/nyct/bus/google_transit_queens.zip,"
        "http://web.mta.info/developers/data/nyct/bus/google_transit_staten_island.zip,"
        "http://web.mta.info/developers/data/busco/google_transit.zip"
    )

    @property
    def bootstrap_area_list(self) -> list[str]:
        return [a.strip() for a in self.sync_bootstrap_areas.split(",") if a.strip()]

    @property
    def mta_bus_static_feed_list(self) -> list[str]:
        urls = self.mta_bus_static_feed_urls.strip() or (
            "http://web.mta.info/developers/data/nyct/bus/google_transit_bronx.zip,"
            "http://web.mta.info/developers/data/nyct/bus/google_transit_brooklyn.zip,"
            "http://web.mta.info/developers/data/nyct/bus/google_transit_manhattan.zip,"
            "http://web.mta.info/developers/data/nyct/bus/google_transit_queens.zip,"
            "http://web.mta.info/developers/data/nyct/bus/google_transit_staten_island.zip,"
            "http://web.mta.info/developers/data/busco/google_transit.zip"
        )
        return [u.strip() for u in urls.split(",") if u.strip()]

    @property
    def resolved_database_url(self) -> str:
        """Pick the right sync DSN, ignoring asyncpg-flavoured DATABASE_URL.

        Priority:
          1. DATABASE_URL_SYNC_DOCKER (compose network)
          2. DATABASE_URL_SYNC (host)
          3. DATABASE_URL — only if it's already a psycopg DSN (i.e. a host
             override didn't accidentally hand us the asyncpg variant)
          4. local default
        """
        if self.database_url_sync_docker:
            return self.database_url_sync_docker
        if self.database_url_sync:
            return self.database_url_sync
        if self.database_url and "+psycopg" in self.database_url:
            return self.database_url
        return "postgresql+psycopg://nyc_agent:nyc_agent_password@localhost:5432/nyc_agent"


settings = Settings()
