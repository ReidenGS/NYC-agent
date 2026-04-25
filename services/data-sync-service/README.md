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
| POST   | `/sync/run/{job_name}`     | Submit job (async); poll status        |

## Registered jobs (MVP)

- `sync_nta` — NTA 2020 boundaries from Socrata `9nt8-h7nd` → `app_area_dimension`
- `sync_nypd_crime` — NYPD complaints from Socrata `qgea-i56i` → `app_crime_incident_snapshot` (PostGIS spatial assignment to NTA) + aggregate `crime_count_30d` into `app_area_metrics_daily`
- `sync_overpass_poi` — OpenStreetMap POIs (entertainment + convenience) via Overpass within the union bbox of seed NTAs → `app_map_poi_snapshot` + aggregate to `app_area_entertainment_category_daily` and `app_area_convenience_category_daily`. Categories per docs/NYC_Agent_Data_Sources_API_SQL.md §6.2.
- `sync_mta_static` — MTA Subway station dictionary from NYS Open Data `39hk-dx4f` → `app_transit_stop_dimension` (mode=subway) + aggregate `transit_station_count` per NTA into `app_area_metrics_daily`. Static data only — realtime arrivals are out of scope and handled by `mcp-transit` via Redis short cache.

(RentCast, Facilities, 311, etc. land in subsequent rounds.)

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
