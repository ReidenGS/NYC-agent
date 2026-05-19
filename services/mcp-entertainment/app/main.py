from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.sql_policy import DOMAIN, validate_sql
from nyc_agent_shared.time import now_iso

SERVICE_NAME = f"mcp-{DOMAIN}"

app = FastAPI(title="NYC Agent MCP Entertainment", version="0.1.0")
engine = create_engine(settings.sqlalchemy_database_url, pool_pre_ping=True, pool_size=3, max_overflow=2)


class ToolRequest(BaseModel):
    session_id: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)


def mcp_response(status: str, tool: str, data: Any, *, source_tables: list[str] | None = None, error: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "status": status,
        "tool": tool,
        "data": data,
        "source_tables": source_tables or [],
        "source": [{"name": "postgres", "type": "sql", "timestamp": now_iso()}],
        "timestamp": now_iso(),
        "confidence": 1.0 if status == "success" else 0.0,
        "data_quality": "reference" if status in {"success", "no_data"} else "unknown",
        "error": error,
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/ready")
def ready() -> dict[str, Any]:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db = "ok"
    except Exception as exc:
        db = f"unavailable: {exc}"
    return {"status": "ok" if db == "ok" else "degraded", "dependencies": {"postgres": db}}


@app.get("/tools")
def tools() -> dict[str, list[str]]:
    return {"tools": ["execute_readonly_sql"]}


@app.post("/tools/execute_readonly_sql")
def execute_readonly_sql(request: ToolRequest) -> dict[str, Any]:
    args = request.arguments
    target_table = str(args.get("target_table", "")).strip().lower()
    sql = str(args.get("sql", ""))
    params = args.get("params") or {}
    max_rows = int(args.get("max_rows") or settings.sql_max_rows_default)
    if max_rows > settings.sql_max_rows_default:
        max_rows = settings.sql_max_rows_default

    validation = validate_sql(sql, params, target_table, max_rows=max_rows)
    if not validation.ok:
        return mcp_response(
            "validation_error",
            "execute_readonly_sql",
            None,
            source_tables=validation.source_tables,
            error={
                "code": validation.error_code or "SQL_VALIDATION_FAILED",
                "message": validation.error_message or "SQL validation failed.",
                "retryable": validation.retryable,
            },
        )

    try:
        with engine.begin() as conn:
            conn.execute(text(f"SET LOCAL statement_timeout = {int(settings.sql_statement_timeout_ms)}"))
            result = conn.execute(text(sql), params)
            rows = [dict(row._mapping) for row in result.fetchmany(max_rows)]
    except SQLAlchemyError as exc:
        return mcp_response(
            "execution_error",
            "execute_readonly_sql",
            None,
            source_tables=validation.source_tables,
            error={"code": "SQL_EXECUTION_FAILED", "message": str(exc.__class__.__name__), "retryable": True},
        )

    if not rows:
        response = mcp_response("no_data", "execute_readonly_sql", [], source_tables=validation.source_tables)
        response["message"] = "Query executed successfully, but no rows were found."
        return response
    return mcp_response("success", "execute_readonly_sql", rows, source_tables=validation.source_tables)


try:
    from app.mcp_server import mcp
    from nyc_agent_shared.mcp_protocol import create_sse_compatible_fastapi_app

    app.mount("/mcp", create_sse_compatible_fastapi_app(mcp))
except Exception as _mcp_mount_exc:  # pragma: no cover
    import logging as _logging

    _logging.getLogger(SERVICE_NAME).warning("MCP mount skipped: %s", _mcp_mount_exc)
