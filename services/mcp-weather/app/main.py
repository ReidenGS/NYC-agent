from __future__ import annotations

from typing import Any

import httpx
from fastapi import FastAPI
from pydantic import BaseModel, Field

from app.config import settings
from nyc_agent_shared.time import now_iso

app = FastAPI(title="NYC Agent MCP Weather", version="0.1.0")

AREA_COORDS = {
    "QN0101": {"area_name": "Astoria", "latitude": 40.7644, "longitude": -73.9235},
    "QN0102": {"area_name": "Long Island City", "latitude": 40.7447, "longitude": -73.9485},
    "BK0101": {"area_name": "Williamsburg", "latitude": 40.7081, "longitude": -73.9571},
    "BK0102": {"area_name": "Greenpoint", "latitude": 40.7306, "longitude": -73.9540},
    "MN0101": {"area_name": "Midtown", "latitude": 40.7549, "longitude": -73.9840},
}


class ToolRequest(BaseModel):
    session_id: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)


def mcp_response(status: str, tool: str, data: Any, *, error: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "status": status,
        "tool": tool,
        "data": data,
        "source": [{"name": "National Weather Service API", "type": "weather_api", "url": "https://api.weather.gov", "timestamp": now_iso()}],
        "timestamp": now_iso(),
        "confidence": 1.0 if status == "success" else 0.0,
        "data_quality": "realtime" if status == "success" else "unknown",
        "error": error,
    }


def resolve_coords(args: dict[str, Any]) -> dict[str, Any] | None:
    if args.get("latitude") is not None and args.get("longitude") is not None:
        return {"latitude": float(args["latitude"]), "longitude": float(args["longitude"]), "area_name": args.get("area_name")}
    area_id = args.get("area_id")
    if area_id and area_id in AREA_COORDS:
        return AREA_COORDS[area_id]
    area_name = str(args.get("area_name") or "").lower()
    for coords in AREA_COORDS.values():
        if area_name and area_name in coords["area_name"].lower():
            return coords
    return None


def nws_get(url: str) -> dict[str, Any]:
    headers = {"User-Agent": settings.nws_user_agent, "Accept": "application/geo+json, application/json"}
    with httpx.Client(timeout=settings.request_timeout_seconds, headers=headers) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.json()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "mcp-weather"}


@app.get("/ready")
def ready() -> dict[str, Any]:
    return {"status": "ok", "dependencies": {"nws": "on_demand"}}


@app.get("/tools")
def tools() -> dict[str, list[str]]:
    return {"tools": ["get_current_weather", "get_hourly_forecast"]}


@app.post("/tools/get_current_weather")
def get_current_weather(request: ToolRequest) -> dict[str, Any]:
    coords = resolve_coords(request.arguments)
    if not coords:
        return mcp_response("validation_error", "get_current_weather", None, error={"code": "MISSING_ARGUMENT", "message": "area_id or latitude/longitude is required.", "retryable": False})
    try:
        points = nws_get(f"https://api.weather.gov/points/{coords['latitude']},{coords['longitude']}")
        hourly_url = points["properties"]["forecastHourly"]
        hourly = nws_get(hourly_url)
        periods = hourly["properties"].get("periods", [])
    except Exception as exc:
        return mcp_response("dependency_failed", "get_current_weather", None, error={"code": "NWS_API_ERROR", "message": str(exc.__class__.__name__), "retryable": True})
    if not periods:
        return mcp_response("no_data", "get_current_weather", None)
    first = periods[0]
    return mcp_response("success", "get_current_weather", {
        "area_name": coords.get("area_name"),
        "latitude": coords["latitude"],
        "longitude": coords["longitude"],
        "temperature": first.get("temperature"),
        "temperature_unit": first.get("temperatureUnit"),
        "short_forecast": first.get("shortForecast"),
        "wind_speed": first.get("windSpeed"),
        "wind_direction": first.get("windDirection"),
        "start_time": first.get("startTime"),
        "end_time": first.get("endTime"),
    })


@app.post("/tools/get_hourly_forecast")
def get_hourly_forecast(request: ToolRequest) -> dict[str, Any]:
    coords = resolve_coords(request.arguments)
    hours = max(1, min(int(request.arguments.get("hours") or 6), 24))
    if not coords:
        return mcp_response("validation_error", "get_hourly_forecast", None, error={"code": "MISSING_ARGUMENT", "message": "area_id or latitude/longitude is required.", "retryable": False})
    try:
        points = nws_get(f"https://api.weather.gov/points/{coords['latitude']},{coords['longitude']}")
        hourly = nws_get(points["properties"]["forecastHourly"])
        periods = hourly["properties"].get("periods", [])[:hours]
    except Exception as exc:
        return mcp_response("dependency_failed", "get_hourly_forecast", None, error={"code": "NWS_API_ERROR", "message": str(exc.__class__.__name__), "retryable": True})
    return mcp_response("success" if periods else "no_data", "get_hourly_forecast", {"area_name": coords.get("area_name"), "periods": periods})
