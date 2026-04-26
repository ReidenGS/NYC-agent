from __future__ import annotations

from typing import Any

import httpx
from fastapi import FastAPI

from app.config import settings
from nyc_agent_shared.prompt_loader import list_prompts, load_prompt
from nyc_agent_shared.schemas import A2ARequest, A2AResponse, ApiError

app = FastAPI(title="NYC Agent Profile Agent", version="0.1.0")

TOOL_BY_TASK = {
    "profile.create_session": "create_session",
    "profile.get_snapshot": "get_snapshot",
    "profile.patch_slots": "patch_slots",
    "profile.update_weights": "update_weights",
    "profile.update_comparison_areas": "update_comparison_areas",
    "profile.save_conversation_summary": "save_conversation_summary",
    "profile.save_last_response_refs": "save_last_response_refs",
    "profile.delete_session": "delete_session",
}


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "service": "profile-agent", "prompts_loaded": len(list_prompts())}


@app.get("/ready")
def ready() -> dict[str, Any]:
    try:
        with httpx.Client(timeout=settings.request_timeout_seconds) as client:
            response = client.get(f"{settings.mcp_profile_url.rstrip('/')}/health")
            response.raise_for_status()
        mcp = "ok"
    except Exception as exc:
        mcp = f"unavailable: {exc}"
    return {"status": "ok" if mcp == "ok" else "degraded", "dependencies": {"mcp-profile": mcp}}


@app.get("/debug/prompts")
def debug_prompts() -> dict[str, Any]:
    names = list_prompts()
    preview = load_prompt("profile/tool_plan_prompt.txt")[:300] if "profile/tool_plan_prompt.txt" in names else None
    return {"prompts": names, "profile_prompt_preview": preview}


def _a2a_error(req: A2ARequest, code: str, message: str, retryable: bool = False) -> A2AResponse:
    return A2AResponse(
        trace_id=req.trace_id,
        session_id=req.session_id,
        source_agent="profile-agent",
        target_agent=req.source_agent,
        task_type=req.task_type,
        status="error",
        payload={},
        error=ApiError(code=code, message=message, retryable=retryable),
    )


def _call_tool(tool: str, session_id: str | None, arguments: dict[str, Any]) -> dict[str, Any]:
    with httpx.Client(timeout=settings.request_timeout_seconds) as client:
        response = client.post(
            f"{settings.mcp_profile_url.rstrip('/')}/tools/{tool}",
            json={"session_id": session_id, "arguments": arguments},
        )
        response.raise_for_status()
        return response.json()


@app.post("/a2a", response_model=A2AResponse)
def handle_a2a(req: A2ARequest) -> A2AResponse:
    tool = TOOL_BY_TASK.get(req.task_type)
    if not tool:
        return _a2a_error(req, "UNSUPPORTED_TASK", f"unsupported profile task: {req.task_type}")

    try:
        arguments = req.payload.get("patch") or req.payload.get("arguments") or req.payload
        result = _call_tool(tool, req.session_id, arguments)
    except httpx.HTTPStatusError as exc:
        detail = exc.response.json().get("detail", {}) if exc.response.content else {}
        error = detail.get("error") or {}
        return A2AResponse(
            trace_id=req.trace_id,
            session_id=req.session_id,
            source_agent="profile-agent",
            target_agent=req.source_agent,
            task_type=req.task_type,
            status="dependency_failed",
            payload={"mcp_detail": detail},
            error=ApiError(
                code=error.get("code", "MCP_PROFILE_ERROR"),
                message=error.get("message", str(exc)),
                retryable=False,
            ),
        )
    except Exception as exc:
        return _a2a_error(req, "MCP_PROFILE_UNAVAILABLE", str(exc), retryable=True)

    profile = result.get("data", {}).get("profile_snapshot")
    status = "success" if result.get("status") == "success" else "error"
    return A2AResponse(
        trace_id=req.trace_id,
        session_id=(profile or {}).get("session_id", req.session_id),
        source_agent="profile-agent",
        target_agent=req.source_agent,
        task_type=req.task_type,
        status=status,
        payload={"profile_snapshot": profile, "mcp_result": result},
        error=None,
    )
