# data-sync-service

Independent FastAPI service that pulls external data (NYC Open Data, RentCast, etc.)
into PostgreSQL + PostGIS. Does **not** participate in user chat / A2A / MCP.

Spec: [NYC_Agent_Data_Sync_Design.md](../../NYC_Agent_Data_Sync_Design.md)

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

(Overpass, RentCast, MTA, etc. land in subsequent rounds.)

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
