"""Cut 8 — FastMCP layer for mcp-weather.

Mirrors the existing FastAPI `/tools/*` routes as `@mcp.tool()` registrations
so this service can be discovered by any MCP client (Claude Desktop, MCP
Inspector, etc.). The two surfaces share the same underlying logic — main.py
keeps the legacy REST routes; this module exposes them via MCP protocol.
"""
from __future__ import annotations

from typing import Any

from app.main import get_current_weather as _legacy_current
from app.main import get_hourly_forecast as _legacy_hourly
from nyc_agent_shared.mcp_protocol import build_mcp_server

mcp = build_mcp_server("mcp-weather")


# Both legacy handlers take a `ToolRequest` Pydantic body. To make them
# callable from FastMCP's positional-args protocol, we accept plain kwargs
# here and reconstruct the ToolRequest internally.
def _wrap_request(arguments: dict[str, Any]):
    from app.main import ToolRequest  # local import to avoid circular at import-time
    return ToolRequest(arguments=arguments)


@mcp.tool(name="get_current_weather", description="Current weather for an NYC area or lat/lon.")
def get_current_weather(area_id: str | None = None,
                         latitude: float | None = None,
                         longitude: float | None = None) -> dict[str, Any]:
    args: dict[str, Any] = {}
    if area_id:
        args["area_id"] = area_id
    if latitude is not None:
        args["latitude"] = latitude
    if longitude is not None:
        args["longitude"] = longitude
    return _legacy_current(_wrap_request(args))


@mcp.tool(name="get_hourly_forecast", description="Hourly forecast (1-24h) for an NYC area or lat/lon.")
def get_hourly_forecast(area_id: str | None = None, hours: int = 6,
                        latitude: float | None = None,
                        longitude: float | None = None) -> dict[str, Any]:
    args: dict[str, Any] = {"hours": hours}
    if area_id:
        args["area_id"] = area_id
    if latitude is not None:
        args["latitude"] = latitude
    if longitude is not None:
        args["longitude"] = longitude
    return _legacy_hourly(_wrap_request(args))
