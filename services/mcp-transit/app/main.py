from __future__ import annotations

from typing import Any

import httpx
from fastapi import FastAPI
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.commute import build_commute_result
from app.config import settings
from app.realtime import refresh_predictions
from nyc_agent_shared.time import now_iso

app = FastAPI(title="NYC Agent MCP Transit", version="0.1.0")
engine = create_engine(settings.sqlalchemy_database_url, pool_pre_ping=True, pool_size=3, max_overflow=2)


class ToolRequest(BaseModel):
    session_id: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)


def mcp_response(status: str, tool: str, data: Any, *, error: dict[str, Any] | None = None, source_tables: list[str] | None = None) -> dict[str, Any]:
    return {
        "status": status,
        "tool": tool,
        "data": data,
        "source_tables": source_tables or [],
        "source": [{"name": "mcp-transit", "type": "fixed_tool", "timestamp": now_iso()}],
        "timestamp": now_iso(),
        "confidence": 1.0 if status == "success" else 0.0,
        "data_quality": "realtime" if status == "success" else "no_data" if status == "no_data" else "unknown",
        "error": error,
    }


def db_rows(sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    with engine.begin() as conn:
        conn.execute(text(f"SET LOCAL statement_timeout = {int(settings.transit_statement_timeout_ms)}"))
        result = conn.execute(text(sql), params)
        return [dict(row._mapping) for row in result.fetchall()]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "mcp-transit"}


@app.get("/ready")
def ready() -> dict[str, Any]:
    try:
        db_rows("SELECT 1 AS ok", {})
        db = "ok"
    except Exception as exc:
        db = f"unavailable: {exc}"
    realtime = {
        "enabled": settings.transit_realtime_enabled,
        "subway_feed": "configured",
        "subway_api_key": "configured" if settings.mta_api_key else "not_configured_optional",
        "bus_api_key": "configured" if settings.mta_bus_time_api_key else "not_configured",
    }
    return {"status": "ok" if db == "ok" else "degraded", "dependencies": {"postgres": db, "mta_realtime": realtime}}


@app.get("/tools")
def tools() -> dict[str, list[str]]:
    return {"tools": ["resolve_station_or_stop", "get_next_departures", "get_realtime_commute"]}


@app.post("/tools/resolve_station_or_stop")
def resolve_station_or_stop(request: ToolRequest) -> dict[str, Any]:
    args = request.arguments
    stop_name = str(args.get("stop_name") or args.get("station_name") or "").strip()
    mode = str(args.get("mode") or "subway").strip().lower()
    if not stop_name:
        return mcp_response("validation_error", "resolve_station_or_stop", None, error={"code": "MISSING_ARGUMENT", "message": "stop_name or station_name is required.", "retryable": False})
    try:
        rows = db_rows(
            "SELECT stop_id, stop_name, mode, latitude, longitude, parent_station_id, source "
            "FROM app_transit_stop_dimension "
            "WHERE mode = :mode AND stop_name ILIKE :stop_name "
            "ORDER BY stop_name ASC LIMIT 10",
            {"mode": mode, "stop_name": f"%{stop_name}%"},
        )
    except SQLAlchemyError:
        return mcp_response("execution_error", "resolve_station_or_stop", None, error={"code": "DB_ERROR", "message": "station lookup failed.", "retryable": True}, source_tables=["app_transit_stop_dimension"])
    if not rows:
        return mcp_response("no_data", "resolve_station_or_stop", [], source_tables=["app_transit_stop_dimension"])
    return mcp_response("success", "resolve_station_or_stop", {"stops": rows}, source_tables=["app_transit_stop_dimension"])


@app.post("/tools/get_next_departures")
def get_next_departures(request: ToolRequest) -> dict[str, Any]:
    args = request.arguments
    mode = str(args.get("mode") or "").strip().lower()
    route_id = str(args.get("route_id") or "").strip().upper()
    stop_id = str(args.get("stop_id") or "").strip()
    limit = max(1, min(int(args.get("limit") or 2), 5))
    if not mode or not route_id or not stop_id:
        return mcp_response("validation_error", "get_next_departures", None, error={"code": "MISSING_ARGUMENT", "message": "mode, route_id and stop_id are required.", "retryable": False})
    refresh_meta: dict[str, Any] | None = None
    try:
        with engine.begin() as conn:
            conn.execute(text(f"SET LOCAL statement_timeout = {int(settings.transit_statement_timeout_ms)}"))
            refresh_meta = refresh_predictions(conn, mode=mode, route_id=route_id, stop_id=stop_id)
    except (SQLAlchemyError, httpx.HTTPError, ValueError) as exc:
        refresh_meta = {"enabled": settings.transit_realtime_enabled, "error": type(exc).__name__, "message": str(exc), "retryable": True}
    except Exception as exc:
        refresh_meta = {"enabled": settings.transit_realtime_enabled, "error": type(exc).__name__, "message": "unexpected realtime refresh failure", "retryable": True}
    try:
        rows = db_rows(
            "SELECT prediction_id, mode, stop_id, route_id, trip_id, direction_id, arrival_time, departure_time, "
            "delay_seconds, prediction_rank, source, feed_timestamp, fetched_at, expires_at "
            "FROM app_transit_realtime_prediction "
            "WHERE mode = :mode AND route_id = :route_id AND stop_id = :stop_id AND expires_at >= NOW() "
            "ORDER BY COALESCE(departure_time, arrival_time) ASC LIMIT :limit",
            {"mode": mode, "route_id": route_id, "stop_id": stop_id, "limit": limit},
        )
    except SQLAlchemyError:
        return mcp_response("execution_error", "get_next_departures", None, error={"code": "DB_ERROR", "message": "departure query failed.", "retryable": True}, source_tables=["app_transit_realtime_prediction"])
    if not rows:
        return mcp_response("no_data", "get_next_departures", {"stop_id": stop_id, "route_id": route_id, "mode": mode, "departures": [], "refresh": refresh_meta}, source_tables=["app_transit_realtime_prediction"])
    return mcp_response("success", "get_next_departures", {"stop_id": stop_id, "route_id": route_id, "mode": mode, "departures": rows, "refresh": refresh_meta}, source_tables=["app_transit_realtime_prediction"])


@app.post("/tools/get_realtime_commute")
def get_realtime_commute(request: ToolRequest) -> dict[str, Any]:
    args = request.arguments
    origin = str(args.get("origin") or "").strip()
    destination = str(args.get("destination") or "").strip()
    mode = str(args.get("mode") or "").strip().lower()
    route_id = str(args.get("route_id") or "").strip().upper() or None
    if not origin or not destination or not mode:
        return mcp_response("validation_error", "get_realtime_commute", None, error={"code": "MISSING_ARGUMENT", "message": "origin, destination and mode are required.", "retryable": False})
    try:
        with engine.begin() as conn:
            conn.execute(text(f"SET LOCAL statement_timeout = {int(settings.transit_statement_timeout_ms)}"))
            result = build_commute_result(
                conn,
                session_id=request.session_id,
                origin=origin,
                destination=destination,
                mode=mode,
                route_id=route_id,
            )
    except SQLAlchemyError:
        return mcp_response("execution_error", "get_realtime_commute", None, error={"code": "DB_ERROR", "message": "commute query failed.", "retryable": True}, source_tables=["app_transit_trip_result_cache"])
    except (httpx.HTTPError, ValueError) as exc:
        return mcp_response("execution_error", "get_realtime_commute", None, error={"code": "TRANSIT_REFRESH_ERROR", "message": str(exc), "retryable": True}, source_tables=["app_transit_trip_result_cache", "app_transit_stop_dimension", "app_transit_realtime_prediction"])
    if not result:
        return mcp_response("no_data", "get_realtime_commute", None, source_tables=["app_transit_trip_result_cache"])
    return mcp_response("success", "get_realtime_commute", result, source_tables=["app_transit_trip_result_cache", "app_transit_stop_dimension", "app_transit_realtime_prediction"])
