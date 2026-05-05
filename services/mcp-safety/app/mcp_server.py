from __future__ import annotations

from typing import Any

from app.main import execute_readonly_sql as _legacy_exec
from nyc_agent_shared.mcp_protocol import build_mcp_server

mcp = build_mcp_server("mcp-safety")


def _wrap_request(arguments: dict[str, Any], session_id: str | None = None):
    from app.main import ToolRequest
    return ToolRequest(session_id=session_id, arguments=arguments)


@mcp.tool(
    name="execute_readonly_sql",
    description="Execute safety readonly SQL against whitelisted tables.",
)
def execute_readonly_sql(
    target_table: str,
    sql: str,
    params: dict[str, Any] | None = None,
    max_rows: int = 25,
    session_id: str | None = None,
) -> dict[str, Any]:
    return _legacy_exec(
        _wrap_request(
            {"target_table": target_table, "sql": sql, "params": params or {}, "max_rows": max_rows},
            session_id=session_id,
        )
    )
