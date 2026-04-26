from __future__ import annotations

from typing import Any

import httpx
from fastapi import FastAPI

from app.config import settings
from nyc_agent_shared.prompt_loader import list_prompts, load_prompt
from nyc_agent_shared.schemas import A2ARequest, A2AResponse, ApiError

app = FastAPI(title="NYC Agent Transit Agent", version="0.1.0")


def slot(slots: dict[str, Any], key: str) -> Any:
    value = slots.get(key)
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    return value


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "service": "transit-agent", "prompts_loaded": len(list_prompts())}


@app.get("/ready")
def ready() -> dict[str, Any]:
    try:
        with httpx.Client(timeout=settings.request_timeout_seconds) as client:
            response = client.get(f"{settings.mcp_transit_url.rstrip('/')}/ready")
            response.raise_for_status()
        mcp = "ok"
    except Exception as exc:
        mcp = f"unavailable: {exc}"
    return {"status": "ok" if mcp == "ok" else "degraded", "dependencies": {"mcp-transit": mcp}}


@app.get("/debug/prompts")
def debug_prompts() -> dict[str, Any]:
    names = list_prompts()
    preview = load_prompt("transit/tool_plan_prompt.txt")[:300] if "transit/tool_plan_prompt.txt" in names else None
    return {"prompts": names, "transit_prompt_preview": preview}


def a2a_error(req: A2ARequest, code: str, message: str, status: str = "error", retryable: bool = False, payload: dict[str, Any] | None = None) -> A2AResponse:
    return A2AResponse(
        trace_id=req.trace_id,
        session_id=req.session_id,
        source_agent="transit-agent",
        target_agent=req.source_agent,
        task_type=req.task_type,
        status=status,  # type: ignore[arg-type]
        payload=payload or {},
        error=ApiError(code=code, message=message, retryable=retryable),
    )


def call_tool(tool: str, session_id: str | None, arguments: dict[str, Any]) -> dict[str, Any]:
    with httpx.Client(timeout=settings.request_timeout_seconds) as client:
        response = client.post(
            f"{settings.mcp_transit_url.rstrip('/')}/tools/{tool}",
            json={"session_id": session_id, "arguments": arguments},
        )
        response.raise_for_status()
        return response.json()


def require_slots(req: A2ARequest, slots: dict[str, Any], required: list[str]) -> A2AResponse | None:
    missing = [key for key in required if not slot(slots, key)]
    if missing:
        prompts = {
            "mode": "你想查地铁、公交，还是两种都可以？",
            "route_id": "你想查哪条线路？例如 N、7、Q69。",
            "stop_name": "你想查哪个站点或公交站？",
            "direction": "你想查往哪个方向的车？例如往 Manhattan。",
            "origin": "你从哪里出发？",
            "destination": "你要去哪里？",
        }
        first = missing[0]
        return A2AResponse(
            trace_id=req.trace_id,
            session_id=req.session_id,
            source_agent="transit-agent",
            target_agent=req.source_agent,
            task_type=req.task_type,
            status="clarification_required",
            payload={"missing_slots": missing, "clarification": prompts.get(first, f"缺少 {first}。")},
            error=None,
        )
    return None


@app.post("/a2a", response_model=A2AResponse)
def handle_a2a(req: A2ARequest) -> A2AResponse:
    if not req.task_type.startswith("transit."):
        return a2a_error(req, "UNSUPPORTED_TASK", f"unsupported transit task: {req.task_type}")
    slots = req.payload.get("slots") or {}

    try:
        if req.task_type == "transit.next_departure":
            missing = require_slots(req, slots, ["mode", "route_id", "stop_name", "direction"])
            if missing:
                return missing
            resolved = call_tool("resolve_station_or_stop", req.session_id, {"mode": slot(slots, "mode"), "stop_name": slot(slots, "stop_name")})
            stops = ((resolved.get("data") or {}).get("stops") or []) if resolved.get("status") == "success" else []
            if not stops:
                return A2AResponse(
                    trace_id=req.trace_id,
                    session_id=req.session_id,
                    source_agent="transit-agent",
                    target_agent=req.source_agent,
                    task_type=req.task_type,
                    status="no_data",
                    payload={"transit_result": {"status": "no_data", "reason": "station_not_found"}, "tool_results": [resolved]},
                    error=None,
                )
            stop_id = stops[0]["stop_id"]
            departures = call_tool("get_next_departures", req.session_id, {"mode": slot(slots, "mode"), "route_id": slot(slots, "route_id"), "stop_id": stop_id, "limit": 2})
            result = {
                "status": "success" if departures.get("status") == "success" else "no_data",
                "domain": "transit",
                "task_type": req.task_type,
                "transit_result_type": "next_departure",
                "derived_metrics": {
                    "mode": slot(slots, "mode"),
                    "route_id": slot(slots, "route_id"),
                    "stop_name": stops[0]["stop_name"],
                    "direction": slot(slots, "direction"),
                    "departures": (departures.get("data") or {}).get("departures", []),
                },
                "data_context": {"realtime_used": departures.get("status") == "success", "fallback_used": False},
                "display_refs": {"route_layer_id": None},
            }
            return A2AResponse(trace_id=req.trace_id, session_id=req.session_id, source_agent="transit-agent", target_agent=req.source_agent, task_type=req.task_type, status="success" if result["status"] == "success" else "no_data", payload={"transit_result": result, "tool_results": [resolved, departures]}, error=None)  # type: ignore[arg-type]

        if req.task_type in {"transit.commute_time", "transit.realtime_commute"}:
            missing = require_slots(req, slots, ["origin", "destination", "mode"])
            if missing:
                return missing
            commute_args = {"origin": slot(slots, "origin"), "destination": slot(slots, "destination"), "mode": slot(slots, "mode")}
            if slot(slots, "route_id"):
                commute_args["route_id"] = slot(slots, "route_id")
            commute = call_tool("get_realtime_commute", req.session_id, commute_args)
            result = {
                "status": "success" if commute.get("status") == "success" else "no_data",
                "domain": "transit",
                "task_type": req.task_type,
                "transit_result_type": "realtime_commute",
                "derived_metrics": commute.get("data") or {"origin": slot(slots, "origin"), "destination": slot(slots, "destination"), "mode": slot(slots, "mode")},
                "data_context": {"realtime_used": bool((commute.get("data") or {}).get("realtime_used")), "fallback_used": bool((commute.get("data") or {}).get("fallback_used"))},
                "display_refs": {"route_layer_id": None},
            }
            return A2AResponse(trace_id=req.trace_id, session_id=req.session_id, source_agent="transit-agent", target_agent=req.source_agent, task_type=req.task_type, status="success" if result["status"] == "success" else "no_data", payload={"transit_result": result, "tool_results": [commute]}, error=None)  # type: ignore[arg-type]
    except Exception as exc:
        return a2a_error(req, "MCP_TRANSIT_UNAVAILABLE", str(exc), status="dependency_failed", retryable=True)

    return a2a_error(req, "UNSUPPORTED_TASK", f"unsupported transit task: {req.task_type}", status="unsupported_data_request")
