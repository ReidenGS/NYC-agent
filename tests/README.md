# Tests

138 tests covering unit, integration, and e2e layers. Total runtime ~25s
when the full docker stack is up.

## Quick start

```bash
make venv           # one-time: creates .venv + installs pytest/httpx/sqlalchemy
make up             # docker stack must be running
make bootstrap      # one-time: seeds NTAs/crime/POI/MTA/etc into postgres
make test           # all 138 tests
```

Or directly:

```bash
.venv/bin/pytest tests/ -v
```

## Layout

```
tests/
├── conftest.py                    # shared fixtures: pg_engine, isolated_schema, app-path swap
├── unit/                          # no docker required (except where noted)
│   ├── test_envelope_shape.py            (5)  A1
│   ├── test_mock_data_fallback.py        (8)  A2
│   ├── test_profile_normalization.py     (7)  A5
│   ├── test_llm_planner_guards.py        (17) A6 + H1–H3
│   ├── test_job_run_wrapper.py           (4)  A8
│   ├── test_external_clients.py          (7)  A9
│   └── test_commute_math.py              (5)  A10
├── integration/                   # requires postgres on localhost:5432
│   ├── test_metric_derivation_sql.py     (5)  A7   — uses ephemeral PG schema
│   ├── test_data_contracts.py            (7)  D    — reads live data
│   └── test_mcp_sql_safety.py            (15) F1–F3 — talks to mcp-sql:8020
├── test_e2e_business_flows.py            (17) C1   — full stack via gateway:8000
├── test_e2e_chat_extensions.py           (4)  C2–C5
└── test_llm_planner_fallback.py          (2)  legacy / pre-existing
```

## Test categories

| Tag | What | Needs |
|---|---|---|
| **unit** | Pure-Python helpers (intent classifier, validators, math, mocked HTTP clients) | nothing |
| **integration/derivation** | crime_index_100 / rent_index_value SQL correctness | postgres on `:5432` |
| **integration/contracts** | Live DB invariants (every NTA has rent, crime_index in [0,100], etc.) | postgres + bootstrap done |
| **integration/safety** | mcp-sql refuses non-SELECT, missing LIMIT, non-whitelisted tables | `mcp-sql:8020` up |
| **e2e** | Full chat → orchestrator → domain agent → MCP → DB round-trips | full stack up |

## Environment overrides

All defaults assume the standard docker compose ports. Override via env if your
setup differs:

| Variable | Default |
|---|---|
| `GATEWAY_URL` | `http://localhost:8000` |
| `DATA_SYNC_URL` | `http://localhost:8030` |
| `MCP_SQL_URL` | `http://localhost:8020` |
| `TEST_PG_URL` | `postgresql+psycopg://nyc_agent:nyc_agent_password@localhost:5432/nyc_agent` |
| `SAMPLE_AREA` | `QN0101` (Astoria) |
| `PEER_AREA` | `BK0101` (Williamsburg) |

## Common failures and what they mean

| Symptom | Likely cause | Fix |
|---|---|---|
| `ECONNREFUSED localhost:8000` | gateway not up | `make up` |
| `relation v_sync_freshness does not exist` | postgres volume predates a schema change | `psql -f db/init/002_schema.sql` (re-applies idempotent DDL) |
| `crime_index_100 = 0` everywhere | `sync_nypd_crime` ran but pre-dates the INDEX_REFRESH_SQL fix | re-trigger: `curl -X POST http://localhost:8030/sync/run/sync_nypd_crime` |
| e2e tests hang for 45s on a chat call | LLM planner timing out | check `OPENAI_API_KEY` in `.env`, or set `USE_LLM_SQL_PLANNER=false` to use deterministic fallback |
| Tests pass alone but fail when run together | another test polluted `app.*` import path | use `add_service_to_path()` / `add_gateway_to_path()` from conftest in module fixtures (already done) |

## Subset shortcuts

```bash
make test-unit          # unit only — fastest, no docker
make test-integration   # everything in tests/integration/
make test-e2e           # full chat round-trips through the stack

# Single file
.venv/bin/pytest tests/integration/test_data_contracts.py -v

# Single test
.venv/bin/pytest tests/unit/test_envelope_shape.py::test_success_envelope_serializes_with_data -v

# Stop on first failure, show locals
.venv/bin/pytest tests/ -x --tb=long --showlocals
```

## Adding new tests

- Pure logic → `tests/unit/`. Stub I/O with `httpx.MockTransport` or `monkeypatch`.
- DB derivation correctness → `tests/integration/`, use the `isolated_schema` fixture so you don't pollute live data.
- DB invariants on real data → `tests/integration/test_data_contracts.py`, use `pg_engine` (read-only).
- New chat flow → extend `tests/test_e2e_chat_extensions.py`.

If your test imports from a service's `app.*` package, get the path through conftest:

```python
from tests.conftest import add_service_to_path  # for services/<name>/
from tests.conftest import add_gateway_to_path  # for backend/api-gateway/
```

Don't manipulate `sys.path` directly — multiple service `app/` packages will collide.
