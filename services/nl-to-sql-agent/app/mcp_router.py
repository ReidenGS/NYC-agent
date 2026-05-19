from __future__ import annotations

import asyncio
import json
from typing import Any

from python_a2a.mcp import MCPClient

from app.tool_registry import get_mcp_sql_tool


def _validate_query_tool(query: dict[str, Any]):
    tool_id = str(query.get("mcp_tool") or "").strip()
    if not tool_id:
        raise ValueError("query mcp_tool is required.")
    tool = get_mcp_sql_tool(tool_id)

    query_domain = str(query.get("domain") or "").strip().lower()
    if query_domain not in tool.domains:
        raise ValueError(f"query domain {query_domain!r} is not allowed for {tool.tool_id}.")

    target_table = str(query.get("target_table") or "").strip().lower()
    if target_table not in tool.target_tables:
        raise ValueError(f"query target_table {target_table!r} is not allowed for {tool.tool_id}.")
    return tool


def _extract_mcp_result(response_json: dict[str, Any]) -> dict[str, Any]:
    if response_json.get("error"):
        error = response_json["error"]
        raise ValueError(error.get("message") or "MCP tools/call failed.")
    result = response_json.get("result") or {}
    if result.get("isError"):
        content = result.get("content") or []
        message = content[0].get("text") if content and isinstance(content[0], dict) else "MCP tool returned an error."
        raise ValueError(str(message))
    content = result.get("content") or []
    if len(content) == 1 and isinstance(content[0], dict) and content[0].get("type") == "text":
        text = str(content[0].get("text") or "")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"MCP tool returned non-JSON text: {text[:120]}") from exc
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("MCP tool returned unsupported content.")


def _parse_mcp_client_result(result: Any) -> dict[str, Any]:
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
        except json.JSONDecodeError as exc:
            raise ValueError(f"MCP tool returned non-JSON text: {result[:120]}") from exc
        if isinstance(parsed, dict):
            return parsed
    if isinstance(result, dict):
        return _extract_mcp_result({"result": result})
    if isinstance(result, list):
        return _extract_mcp_result({"result": {"content": result}})
    raise ValueError(f"MCP tool returned unsupported result type: {type(result).__name__}")


def call_mcp_tool(tool_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
    tool = get_mcp_sql_tool(tool_id)
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    client = MCPClient(server_url=f"{tool.base_url.rstrip('/')}/mcp/")
    return _parse_mcp_client_result(client.call_tool_sync(tool.tool_name, **arguments))


def execute_query(session_id: str | None, task_type: str, query: dict[str, Any]) -> dict[str, Any]:
    tool = _validate_query_tool(query)
    args = {
        "target_table": query["target_table"],
        "sql": str(query["sql"]),
        "params": query.get("params", {}) or {},
        "max_rows": 50,
        "session_id": session_id,
    }
    result = call_mcp_tool(tool.tool_id, args)
    return {
        "purpose": query["purpose"],
        "expected_result": query.get("expected_result"),
        "domain": str(query.get("domain") or "").strip().lower(),
        "mcp_tool": tool.tool_id,
        "status": result.get("status"),
        "data": result.get("data") or [],
        "source_tables": result.get("source_tables") or [],
        "error": result.get("error"),
    }
