"""Cut 8 — FastMCP layer for mcp-transit. See mcp-weather/app/mcp_server.py
for the rationale (parallel surface, same underlying logic)."""
from __future__ import annotations

from typing import Any

from app.main import get_next_departures as _legacy_next
from app.main import get_realtime_commute as _legacy_commute
from app.main import resolve_station_or_stop as _legacy_resolve
from nyc_agent_shared.mcp_protocol import build_mcp_server

mcp = build_mcp_server("mcp-transit")


def _wrap_request(arguments: dict[str, Any], session_id: str | None = None):
    from app.main import ToolRequest
    return ToolRequest(session_id=session_id, arguments=arguments)


@mcp.tool(name="resolve_station_or_stop", description="Look up a subway station or bus stop by name.")
def resolve_station_or_stop(stop_name: str, mode: str = "subway") -> dict[str, Any]:
    return _legacy_resolve(_wrap_request({"stop_name": stop_name, "mode": mode}))


@mcp.tool(name="get_next_departures", description="Next N departures at a stop on a route.")
def get_next_departures(mode: str, route_id: str, stop_id: str, limit: int = 2) -> dict[str, Any]:
    return _legacy_next(_wrap_request({
        "mode": mode, "route_id": route_id, "stop_id": stop_id, "limit": limit,
    }))


@mcp.tool(name="get_realtime_commute", description="Estimated realtime commute time A→B.")
def get_realtime_commute(origin: str, destination: str, mode: str,
                          route_id: str | None = None,
                          session_id: str | None = None) -> dict[str, Any]:
    args: dict[str, Any] = {"origin": origin, "destination": destination, "mode": mode}
    if route_id:
        args["route_id"] = route_id
    return _legacy_commute(_wrap_request(args, session_id=session_id))
