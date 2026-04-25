# data-sync-service

Independent FastAPI service that pulls external data (NYC Open Data, RentCast, etc.)
into PostgreSQL + PostGIS. Does **not** participate in user chat / A2A / MCP.

Spec: [docs/NYC_Agent_Data_Sync_Design.md](../../docs/NYC_Agent_Data_Sync_Design.md)

## Endpoints

| Method | Path                       | Purpose                                |
|--------|----------------------------|----------------------------------------|
| GET    | `/health`                  | Liveness                               |
| GET    | `/ready`                   | DB + PostGIS reachable                 |
| GET    | `/sync/jobs`               | List registered job names              |
| GET    | `/sync/status?limit=20`    | Read recent rows from `app_data_sync_job_log` |
| POST   | `/sync/run/{job_name}`     | Submit one job (async); poll status. Paid jobs (see below) require `?confirm_paid=yes`. |
| POST   | `/sync/run-bootstrap`      | Submit the bootstrap chain (sync_nta → sync_nypd_crime → sync_overpass_poi → sync_facilities → sync_mta_static → sync_311). RentCast and ZORI are excluded due to cost/api-key constraints. |

### Paid jobs (hard server-side gate)

`sync_rentcast` consumes a paid external API. The HTTP layer refuses to
dispatch it unless the caller explicitly opts in:

```bash
# Probe — returns HTTP 412 with budget preview, NO API call:
curl -X POST http://localhost:8030/sync/run/sync_rentcast

# Actually run it — consumes RentCast quota:
curl -X POST 'http://localhost:8030/sync/run/sync_rentcast?confirm_paid=yes'
```

The 412 response body shows current `month_calls_used`, `monthly_cap`,
and `would_use_up_to` so you can decide before retrying. The bootstrap
chain skips paid jobs by design — only an explicit confirmed request
can spend RentCast quota.

> **Scheduled jobs (APScheduler)**: not implemented yet. The dependency
> is in `requirements.txt` for the upcoming `app/scheduler.py`, but no
> jobs are currently registered against APScheduler. All triggers today
> are manual via the endpoints above. `SYNC_ENABLE_SCHEDULED_JOBS` in
> `.env` is reserved for the future implementation.

## Registered jobs (MVP)

- `sync_nta` — NTA 2020 boundaries from Socrata `9nt8-h7nd` → `app_area_dimension`
- `sync_nypd_crime` — NYPD complaints from Socrata `qgea-i56i` → `app_crime_incident_snapshot` (PostGIS spatial assignment to NTA) + aggregate `crime_count_30d` into `app_area_metrics_daily`
- `sync_overpass_poi` — OpenStreetMap POIs (entertainment + convenience) via Overpass within the union bbox of seed NTAs → `app_map_poi_snapshot` + aggregate to `app_area_entertainment_category_daily` and `app_area_convenience_category_daily`. Categories per docs/NYC_Agent_Data_Sources_API_SQL.md §6.2.
- `sync_mta_static` — MTA Subway station dictionary from NYS Open Data `39hk-dx4f` → `app_transit_stop_dimension` (mode=subway) + aggregate `transit_station_count` per NTA into `app_area_metrics_daily`. Static data only — realtime arrivals are out of scope and handled by `mcp-transit` via Redis short cache.
- `sync_facilities` — NYC Facilities Database `67g2-p84d` filtered to 5 verified facgroups (parks, libraries, K-12 schools, health care, cultural) → `app_map_poi_snapshot` (poi_type=convenience, source=67g2-p84d) + aggregate `facility_count` per category into `app_area_convenience_category_daily`. Coexists with overpass-sourced rows because PK includes source.
- `sync_311` — NYC 311 Service Requests `erm2-nwe9` filtered to noise complaints → aggregate-only path (no snapshot table per design §8). Streams into a TEMP table, runs PostGIS spatial assignment + 30-day count, upserts `complaint_noise_30d` into `app_area_metrics_daily`.
- `sync_zori_hud` — Zillow ZORI ZIP-level rent benchmark CSV with NYC modzcta-derived ZIP→NTA mapping → `app_area_rent_benchmark_monthly` (benchmark_type=zori, benchmark_geo_type=zip, bedroom_type=all). Last 24 months ingested.
- `sync_rentcast` — RentCast `/listings/rental/long-term` (manual trigger only, X-Api-Key required) → `app_area_rental_listing_snapshot` + aggregate `rent_min/median/max + listing_count` per (area_id, today, bedroom_type) into `app_area_rental_market_daily`. Strict cost guards: per-run cap `RENTCAST_MAX_CALLS_PER_RUN`, per-month cap `RENTCAST_MAX_CALLS_PER_MONTH` enforced by summing prior `app_data_sync_job_log.api_calls_used` for the current calendar month.

## Run via docker-compose

```bash
docker compose up -d --build data-sync-service
curl http://localhost:8030/health
curl http://localhost:8030/sync/jobs
curl -X POST http://localhost:8030/sync/run/sync_nta
curl http://localhost:8030/sync/status | jq
```

Verify in psql:

```sql
SELECT COUNT(*) FROM app_area_dimension;
SELECT area_id, area_name, borough
FROM app_area_dimension
WHERE area_name ILIKE '%Astoria%';
```

## Local dev (no docker)

```bash
cd services/data-sync-service
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
DATABASE_URL=postgresql+psycopg://nyc_agent:nyc_agent_dev@localhost:5432/nyc_agent \
  uvicorn app.main:app --reload --port 8030
```
