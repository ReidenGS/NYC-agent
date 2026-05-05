# API Gateway MVP

FastAPI implementation of the frontend-facing API contract for NYC Agent.

Current scope:
- Provides runnable Gateway routes for frontend integration.
- Calls remote `orchestrator-agent` by default for session/profile/chat.
- Keeps a deterministic in-process fallback only when `ALLOW_MOCK_FALLBACK=true`; production/demo runs should keep it `false` so unavailable real services fail visibly.
- Proxies `/areas/{area_id}/map-layers` to `data-sync-service` so the frontend can load pre-generated GeoJSON layers from `app_map_layer_cache`.
- Exposes `/debug/dependencies`, including data-sync freshness when `DATA_SYNC_BASE_URL` is reachable.
- Does not access PostgreSQL/MCP directly; domain work goes through A2A Agent services and MCP services.

Run locally:

```bash
cd backend/api-gateway
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Frontend real API mode:

```env
VITE_API_BASE_URL=http://localhost:8000
VITE_USE_MOCK_API=false
VITE_DEBUG_MODE=true
```

Docker Compose:

```bash
cp .env.example .env
docker compose up -d postgres redis data-sync-service mcp-profile profile-agent mcp-sql housing-agent neighborhood-agent mcp-transit transit-agent mcp-weather weather-agent orchestrator-agent api-gateway
```

Current backend landing status:

- `docker-compose.yml` runs the full local backend graph: Gateway, orchestrator, domain agents, MCP services, data-sync service, PostgreSQL, and Redis.
- PostgreSQL and Redis reuse the existing Docker volumes from `nyc-agent-claude`, so the previously synced NYC data can be used without a new full sync.
- Gateway exposes both root routes and `/api/*` routes. The frontend should use `VITE_API_BASE_URL=http://localhost:8000` and `VITE_USE_MOCK_API=false`.
- Session/profile/chat now go through the remote orchestrator-agent path by default. Mock fallback should stay disabled for backend validation.
- Domain answers are returned through `python-a2a` `Message` responses and summarized by the orchestrator; profile memory persists `target_area_id`, short `conversation_summary`, and last response refs.
- Agent cards are exposed at `/agent.json` for orchestrator, housing, neighborhood, profile, transit, and weather agents.

Useful validation commands:

```bash
docker compose ps
curl -sS http://localhost:8000/api/ready
PYTHONPATH=backend/api-gateway backend/api-gateway/.venv/bin/python -m pytest backend/api-gateway/tests/test_gateway.py backend/api-gateway/tests/test_real_data_paths.py
cd frontend && VITE_USE_MOCK_API=false VITE_API_BASE_URL=http://localhost:8000 npm run build
```

The broader root `tests/unit` suite currently requires additional local Python dependencies such as SQLAlchemy; run it from an environment that has the shared backend/test dependency set installed.

A2A protocol status:

- The six agent services run as Flask apps through `python_a2a.A2AServer`.
- Orchestrator downstream calls use `python_a2a.A2AClient.send_message`.
- Business request/response context is carried inside `Message.content` as `FunctionCallContent` / `FunctionResponseContent`.
- `GET /agent.json` is served by python-a2a's AgentCard route; MVP capabilities advertise synchronous non-streaming responses.

Gateway environment:

```env
API_GATEWAY_PORT=8000
API_GATEWAY_CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
DATA_SYNC_BASE_URL=http://localhost:8030
DATA_SYNC_BASE_URL_DOCKER=http://data-sync-service:8030
USE_REMOTE_ORCHESTRATOR=true
ALLOW_MOCK_FALLBACK=false
ORCHESTRATOR_AGENT_URL=http://localhost:8010
ORCHESTRATOR_AGENT_URL_DOCKER=http://orchestrator-agent:8010
```
