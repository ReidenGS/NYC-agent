from __future__ import annotations

from typing import Any

import httpx
from fastapi import FastAPI

from app.config import settings
from app.housing_logic import build_plan, summarize_results
from nyc_agent_shared.prompt_loader import list_prompts, load_prompt
from nyc_agent_shared.schemas import A2ARequest, A2AResponse, ApiError

app = FastAPI(title="NYC Agent Housing Agent", version="0.1.0")


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "service": "housing-agent", "prompts_loaded": len(list_prompts())}


@app.get("/ready")
def ready() -> dict[str, Any]:
    try:
        with httpx.Client(timeout=settings.request_timeout_seconds) as client:
            response = client.get(f"{settings.mcp_sql_url.rstrip('/')}/ready")
            response.raise_for_status()
        mcp = "ok"
    except Exception as exc:
        mcp = f"unavailable: {exc}"
    return {"status": "ok" if mcp == "ok" else "degraded", "dependencies": {"mcp-sql": mcp}}


@app.get("/debug/prompts")
def debug_prompts() -> dict[str, Any]:
    names = list_prompts()
    preview = load_prompt("housing/sql_plan_prompt.txt")[:300] if "housing/sql_plan_prompt.txt" in names else None
    return {"prompts": names, "housing_prompt_preview": preview}


def _a2a_error(req: A2ARequest, code: str, message: str, status: str = "error", retryable: bool = False, payload: dict[str, Any] | None = None) -> A2AResponse:
    return A2AResponse(
        trace_id=req.trace_id,
        session_id=req.session_id,
        source_agent="housing-agent",
        target_agent=req.source_agent,
        task_type=req.task_type,
        status=status,  # type: ignore[arg-type]
        payload=payload or {},
        error=ApiError(code=code, message=message, retryable=retryable),
    )


def _execute_query(session_id: str | None, query: dict[str, Any]) -> dict[str, Any]:
    args = {
        "domain": "housing",
        "purpose": query["purpose"],
        "sql": query["sql"],
        "params": query.get("params", {}),
        "max_rows": 50,
    }
    with httpx.Client(timeout=settings.request_timeout_seconds) as client:
        response = client.post(
            f"{settings.mcp_sql_url.rstrip('/')}/tools/execute_readonly_sql",
            json={"session_id": session_id, "arguments": args},
        )
        response.raise_for_status()
        result = response.json()
    return {
        "purpose": query["purpose"],
        "expected_result": query.get("expected_result"),
        "status": result.get("status"),
        "data": result.get("data") or [],
        "source_tables": result.get("source_tables") or [],
        "error": result.get("error"),
    }


@app.post("/a2a", response_model=A2AResponse)
def handle_a2a(req: A2ARequest) -> A2AResponse:
    if not req.task_type.startswith("housing."):
        return _a2a_error(req, "UNSUPPORTED_TASK", f"unsupported housing task: {req.task_type}")

    payload = req.payload
    plan = build_plan(
        req.task_type,
        str(payload.get("domain_user_query") or ""),
        payload.get("slots") or {},
        payload.get("domain_context") or {},
    )
    if plan["status"] == "clarification_required":
        return A2AResponse(
            trace_id=req.trace_id,
            session_id=req.session_id,
            source_agent="housing-agent",
            target_agent=req.source_agent,
            task_type=req.task_type,
            status="clarification_required",
            payload=plan,
            error=None,
        )
    if plan["status"] == "unsupported_data_request":
        return A2AResponse(
            trace_id=req.trace_id,
            session_id=req.session_id,
            source_agent="housing-agent",
            target_agent=req.source_agent,
            task_type=req.task_type,
            status="unsupported_data_request",
            payload=plan,
            error=None,
        )

    executions: list[dict[str, Any]] = []
    try:
        for query in plan["queries"]:
            if query["purpose"] == "fallback" and any(item["purpose"] == "analysis" and item["status"] == "success" for item in executions):
                continue
            result = _execute_query(req.session_id, query)
            executions.append(result)
            if result["status"] == "validation_error":
                return _a2a_error(req, "SQL_VALIDATION_FAILED", (result.get("error") or {}).get("message", "SQL validation failed."), status="validation_failed", retryable=True, payload={"sql_plan": plan, "mcp_result": result})
            if result["status"] == "execution_error":
                return _a2a_error(req, "SQL_EXECUTION_FAILED", "mcp-sql execution failed.", status="dependency_failed", retryable=True, payload={"sql_plan": plan, "mcp_result": result})
    except Exception as exc:
        return _a2a_error(req, "MCP_SQL_UNAVAILABLE", str(exc), status="dependency_failed", retryable=True, payload={"sql_plan": plan})

    summary = summarize_results(plan, executions)
    status = "no_data" if summary.get("status") == "no_data" else "success"
    return A2AResponse(
        trace_id=req.trace_id,
        session_id=req.session_id,
        source_agent="housing-agent",
        target_agent=req.source_agent,
        task_type=req.task_type,
        status=status,  # type: ignore[arg-type]
        payload={"sql_plan": plan, "executions": executions, "housing_result": summary},
        error=None,
    )
