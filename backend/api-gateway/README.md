# API Gateway MVP

FastAPI implementation of the frontend-facing API contract for NYC Agent.

Current scope:
- Provides runnable Gateway routes for frontend integration.
- Uses in-memory session/profile state and deterministic mock domain data.
- Keeps Gateway thin: route handlers delegate to `services/orchestrator.py` and mock data services.
- Exposes `/debug/dependencies`, including data-sync freshness when `DATA_SYNC_BASE_URL` is reachable.
- Does not access PostgreSQL/MCP directly yet. Those calls will be swapped to A2A/MCP clients later.

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
docker compose up -d postgres redis data-sync-service api-gateway
```

Gateway environment:

```env
API_GATEWAY_PORT=8000
API_GATEWAY_CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
DATA_SYNC_BASE_URL=http://localhost:8030
DATA_SYNC_BASE_URL_DOCKER=http://data-sync-service:8030
```
