# NYC Agent Frontend

React + TypeScript + Vite frontend for the NYC Agent decision dashboard.

## Run locally

```bash
cd frontend
npm install
npm run dev
```

The Vite config uses `envDir: '..'`, so it reads the project-level `.env` file from the repository root. You can also copy `.env.example` to `frontend/.env.local` if you want frontend-only overrides.

## Important env vars

```env
VITE_API_BASE_URL=http://localhost:8000
VITE_USE_MOCK_API=true
VITE_DEBUG_MODE=true
VITE_MAPTILER_API_KEY=
```

## Architecture

- `src/types/*`: TypeScript contracts aligned with `docs/NYC_Agent_API_Schema_Contract.md`
- `src/api/*`: API client functions with mock/real switching
- `src/mocks/data.ts`: contract-shaped mock responses
- `src/components/*`: dashboard panels, MapLibre map, chat, weather, transit, debug trace
- `src/pages/Dashboard.tsx`: page-level state orchestration
- `prototypes/NYC-agent-prototype.jsx`: original visual prototype kept for reference only

## Map implementation

`MapPanel` uses a real MapLibre GL JS instance. If `VITE_MAPTILER_API_KEY` is set, it loads MapTiler Streets v2. If not set, it falls back to MapLibre demo tiles and shows a visible warning.
