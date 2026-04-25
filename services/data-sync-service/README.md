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
| GET    | `/sync/scheduler`          | Inspect APScheduler state (enabled flag + next-run for each job) |
| POST   | `/sync/run/{job_name}`     | Submit one job (async); poll status. Paid jobs (see below) require `?confirm_paid=yes`. |
| POST   | `/sync/run-bootstrap`      | Submit the bootstrap chain (sync_nta → sync_nypd_crime → sync_overpass_poi → sync_facilities → sync_mta_static → sync_311 → build_map_layers). RentCast and ZORI are excluded due to cost/api-key constraints. |

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

### Scheduled jobs (APScheduler)

Enabled when `SYNC_ENABLE_SCHEDULED_JOBS=true` in `.env`. Triggers reuse
the same single-worker `ThreadPoolExecutor` as `/sync/run/{job_name}` so
manual and scheduled runs serialize through one worker.

Cadence (NYC time, per design §5):

| Cron                        | Jobs |
|-----------------------------|------|
| Daily 02:30 / 02:45         | `sync_nypd_crime`, `sync_311` |
| Sun 03:00 / 03:30 / 04:00   | `sync_facilities`, `sync_overpass_poi`, `sync_mta_static` |
| Sun 04:30                   | `build_map_layers` (after the weekly snapshot wave) |
| 1st of month 04:00 / 04:30  | `sync_nta`, `sync_zori_hud` |
| Oct 5 05:00 (annual)        | `sync_hud_fmr` (after HUD's FY rollover Oct 1) |

`sync_rentcast` is NEVER auto-scheduled — paid APIs only run on an
explicit `/sync/run/sync_rentcast?confirm_paid=yes` call. The scheduler
also `coalesce`s missed firings and uses a 1-hour `misfire_grace_time`,
so a brief container restart won't trigger a thundering herd of catch-up
runs.

Inspect at runtime:
```bash
curl http://localhost:8030/sync/scheduler | jq
```

## Registered jobs (MVP)

- `sync_nta` — NTA 2020 boundaries from Socrata `9nt8-h7nd` → `app_area_dimension`
- `sync_nypd_crime` — NYPD complaints from Socrata `qgea-i56i` → `app_crime_incident_snapshot` (PostGIS spatial assignment to NTA) + aggregate `crime_count_30d` into `app_area_metrics_daily`
- `sync_overpass_poi` — OpenStreetMap POIs (entertainment + convenience) via Overpass within the union bbox of seed NTAs → `app_map_poi_snapshot` + aggregate to `app_area_entertainment_category_daily` and `app_area_convenience_category_daily`. Categories per docs/NYC_Agent_Data_Sources_API_SQL.md §6.2.
- `sync_mta_static` — MTA Subway station dictionary from NYS Open Data `39hk-dx4f` → `app_transit_stop_dimension` (mode=subway) + aggregate `transit_station_count` per NTA into `app_area_metrics_daily`. Static data only — realtime arrivals are out of scope and handled by `mcp-transit` via Redis short cache.
- `sync_facilities` — NYC Facilities Database `67g2-p84d` filtered to 5 verified facgroups (parks, libraries, K-12 schools, health care, cultural) → `app_map_poi_snapshot` (poi_type=convenience, source=67g2-p84d) + aggregate `facility_count` per category into `app_area_convenience_category_daily`. Coexists with overpass-sourced rows because PK includes source.
- `sync_311` — NYC 311 Service Requests `erm2-nwe9` filtered to noise complaints → aggregate-only path (no snapshot table per design §8). Streams into a TEMP table, runs PostGIS spatial assignment + 30-day count, upserts `complaint_noise_30d` into `app_area_metrics_daily`.
- `sync_zori_hud` — Zillow ZORI ZIP-level rent benchmark CSV with NYC modzcta-derived ZIP→NTA mapping → `app_area_rent_benchmark_monthly` (benchmark_type=zori, benchmark_geo_type=zip, bedroom_type=all). Last 24 months ingested. The HUD half of the historical name is now its own job (`sync_hud_fmr`) — both coexist via the PK that includes `benchmark_type`.
- `sync_hud_fmr` — HUD USER Fair Market Rent API (5 NYC counties) → `app_area_rent_benchmark_monthly` (benchmark_type=hud_fmr, benchmark_geo_type=county, bedroom_type=studio/1br/2br/3br/4br, data_quality=official). All 5 NYC counties currently share the metro-wide FMR; we still write 5 distinct rows so `benchmark_geo_id` is honest. Auth via `HUD_USER_API_TOKEN` (free JWT). 5 API calls per run.
- `sync_rentcast` — RentCast `/listings/rental/long-term` (manual trigger only, X-Api-Key required) → `app_area_rental_listing_snapshot` + aggregate `rent_min/median/max + listing_count` per (area_id, today, bedroom_type) into `app_area_rental_market_daily`. Strict cost guards: per-run cap `RENTCAST_MAX_CALLS_PER_RUN`, per-month cap `RENTCAST_MAX_CALLS_PER_MONTH` enforced by summing prior `app_data_sync_job_log.api_calls_used` for the current calendar month.
- `build_map_layers` — pre-generate front-end GeoJSON layers for seed NTAs into `app_map_layer_cache`. Four layers per area: `choropleth · safety` (NTA polygon shaded by crime intensity), `heatmap · crime` (recent crime points capped at 1000), `marker · entertainment` and `marker · convenience` (POIs from `app_map_poi_snapshot`). Each layer ships with a `style_hint` JSON the frontend can read directly. TTL 7 days; failures of one layer don't block others (per design §11). Auto-runs at the end of `/sync/run-bootstrap`.

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
