from __future__ import annotations

from typing import Any

import httpx
from fastapi import FastAPI

from app.config import settings
from nyc_agent_shared.prompt_loader import list_prompts, load_prompt
from nyc_agent_shared.schemas import A2ARequest, A2AResponse, ApiError

app = FastAPI(title="NYC Agent Weather Agent", version="0.1.0")


def slot(slots: dict[str, Any], key: str) -> Any:
    value = slots.get(key)
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    return value


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "service": "weather-agent", "prompts_loaded": len(list_prompts())}


@app.get("/ready")
def ready() -> dict[str, Any]:
    try:
        with httpx.Client(timeout=settings.request_timeout_seconds) as client:
            response = client.get(f"{settings.mcp_weather_url.rstrip('/')}/ready")
            response.raise_for_status()
        mcp = "ok"
    except Exception as exc:
        mcp = f"unavailable: {exc}"
    return {"status": "ok" if mcp == "ok" else "degraded", "dependencies": {"mcp-weather": mcp}}


@app.get("/debug/prompts")
def debug_prompts() -> dict[str, Any]:
    names = list_prompts()
    preview = load_prompt("weather/tool_plan_prompt.txt")[:300] if "weather/tool_plan_prompt.txt" in names else None
    return {"prompts": names, "weather_prompt_preview": preview}


def a2a_error(req: A2ARequest, code: str, message: str, status: str = "error", retryable: bool = False, payload: dict[str, Any] | None = None) -> A2AResponse:
    return A2AResponse(
        trace_id=req.trace_id,
        session_id=req.session_id,
        source_agent="weather-agent",
        target_agent=req.source_agent,
        task_type=req.task_type,
        status=status,  # type: ignore[arg-type]
        payload=payload or {},
        error=ApiError(code=code, message=message, retryable=retryable),
    )


def call_tool(tool: str, session_id: str | None, arguments: dict[str, Any]) -> dict[str, Any]:
    with httpx.Client(timeout=settings.request_timeout_seconds) as client:
        response = client.post(
            f"{settings.mcp_weather_url.rstrip('/')}/tools/{tool}",
            json={"session_id": session_id, "arguments": arguments},
        )
        response.raise_for_status()
        return response.json()


@app.post("/a2a", response_model=A2AResponse)
def handle_a2a(req: A2ARequest) -> A2AResponse:
    if not req.task_type.startswith("weather."):
        return a2a_error(req, "UNSUPPORTED_TASK", f"unsupported weather task: {req.task_type}")
    slots = req.payload.get("slots") or {}
    area_id = slot(slots, "area_id") or slot(slots, "target_area_id")
    area_name = slot(slots, "area_name")
    if not area_id and not (slot(slots, "latitude") and slot(slots, "longitude")):
        return A2AResponse(
            trace_id=req.trace_id,
            session_id=req.session_id,
            source_agent="weather-agent",
            target_agent=req.source_agent,
            task_type=req.task_type,
            status="clarification_required",
            payload={"missing_slots": ["target_area"], "clarification": "你想查哪个区域的天气？"},
            error=None,
        )
    args = {"area_id": area_id, "area_name": area_name, "latitude": slot(slots, "latitude"), "longitude": slot(slots, "longitude"), "hours": req.payload.get("domain_context", {}).get("hours", 6)}
    try:
        tool = "get_hourly_forecast" if req.task_type == "weather.hourly_forecast" else "get_current_weather"
        result = call_tool(tool, req.session_id, args)
    except Exception as exc:
        return a2a_error(req, "MCP_WEATHER_UNAVAILABLE", str(exc), status="dependency_failed", retryable=True)

    if result.get("status") in {"dependency_failed", "validation_error"}:
        return a2a_error(req, (result.get("error") or {}).get("code", "WEATHER_TOOL_ERROR"), (result.get("error") or {}).get("message", "weather tool failed"), status="dependency_failed", retryable=True, payload={"tool_result": result})
    status = "success" if result.get("status") == "success" else "no_data"
    weather_result = {
        "status": status,
        "domain": "weather",
        "task_type": req.task_type,
        "weather_result_type": "hourly_forecast" if tool == "get_hourly_forecast" else "current_weather",
        "derived_metrics": result.get("data"),
        "data_context": {"source": "National Weather Service API", "realtime_used": result.get("status") == "success"},
        "display_refs": {},
    }
    return A2AResponse(
        trace_id=req.trace_id,
        session_id=req.session_id,
        source_agent="weather-agent",
        target_agent=req.source_agent,
        task_type=req.task_type,
        status=status,  # type: ignore[arg-type]
        payload={"weather_result": weather_result, "tool_results": [result]},
        error=None,
    )
