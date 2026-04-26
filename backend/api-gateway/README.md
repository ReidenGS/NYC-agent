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
