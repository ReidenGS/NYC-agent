# Database (PostgreSQL 16 + PostGIS 3.4)

This folder contains everything needed to bring up the shared database
that all NYC Agent services talk to.

## Layout

```
db/
├── README.md              # this file
└── init/                  # auto-run by the postgres container on first boot
    ├── 001_extensions.sql # CREATE EXTENSION postgis
    └── 002_schema.sql     # business tables (mirrors NYC_Agent_Data_Sources_API_SQL.md §6)
```

The `init/` scripts only run on **first** container start (i.e. when the
named volume `nyc_agent_pgdata` is empty). To re-run them you must drop
the volume:

```bash
docker compose down
docker volume rm nyc-agent-claude_nyc_agent_pgdata
docker compose up -d postgres
```

## Quickstart

```bash
# 1. one-time: copy env template and fill secrets
cp .env.example .env

# 2. start the database (and redis)
docker compose up -d postgres redis

# 3. tail logs to confirm init ran
docker compose logs -f postgres   # look for "database system is ready"

# 4. open a psql shell
docker compose exec postgres psql -U nyc_agent -d nyc_agent

# 5. confirm PostGIS and tables exist
\dx                  # should list postgis
\dt app_*            # should list 17 app_* tables
SELECT PostGIS_Full_Version();
```

## Schema source of truth

The DDL in `init/002_schema.sql` is a verbatim copy of the SQL block in
`NYC_Agent_Data_Sources_API_SQL.md` §6. Any schema change must be made
in that markdown first; this file is regenerated from it.

## Connection strings

See `.env.example`. Two canonical DSNs:

- `DATABASE_URL` — for processes running on the host (laptop)
- `DATABASE_URL_DOCKER` — for processes running inside the compose
  network (host = `postgres`)
