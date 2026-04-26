from __future__ import annotations

from typing import Any

import httpx
from fastapi import FastAPI
from pydantic import BaseModel, Field

from app.config import settings
from nyc_agent_shared.time import now_iso

app = FastAPI(title=f"NYC Agent {settings.service_name}", version="0.1.0")


class ToolRequest(BaseModel):
    session_id: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.service_name, "sql_domain": settings.sql_domain}


@app.get("/ready")
def ready() -> dict[str, Any]:
    try:
        with httpx.Client(timeout=settings.request_timeout_seconds) as client:
            response = client.get(f"{settings.mcp_sql_url.rstrip('/')}/ready")
            response.raise_for_status()
        mcp_sql = "ok"
    except Exception as exc:
        mcp_sql = f"unavailable: {exc}"
    return {"status": "ok" if mcp_sql == "ok" else "degraded", "dependencies": {"mcp-sql": mcp_sql}}


@app.get("/tools")
def tools() -> dict[str, list[str]]:
    return {"tools": ["execute_readonly_sql"]}


@app.post("/tools/execute_readonly_sql")
def execute_readonly_sql(request: ToolRequest) -> dict[str, Any]:
    args = dict(request.arguments)
    args["domain"] = settings.sql_domain
    with httpx.Client(timeout=settings.request_timeout_seconds) as client:
        response = client.post(
            f"{settings.mcp_sql_url.rstrip('/')}/tools/execute_readonly_sql",
            json={"session_id": request.session_id, "arguments": args},
        )
        response.raise_for_status()
        result = response.json()
    result["proxied_by"] = {
        "service": settings.service_name,
        "sql_domain": settings.sql_domain,
        "timestamp": now_iso(),
    }
    return result
