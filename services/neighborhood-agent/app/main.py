from __future__ import annotations

from typing import Any

import httpx
from fastapi import FastAPI

from app.config import settings
from app.llm_planner import build_plan
from app.neighborhood_logic import summarize_results
from nyc_agent_shared.prompt_loader import list_prompts, load_prompt
from nyc_agent_shared.schemas import A2ARequest, A2AResponse, ApiError

app = FastAPI(title="NYC Agent Neighborhood Agent", version="0.1.0")


@app.get("/health")
def health() -> dict[str, Any]:
    planner = "llm_optional" if settings.use_llm_sql_planner else "deterministic"
    return {"status": "ok", "service": "neighborhood-agent", "prompts_loaded": len(list_prompts()), "sql_planner": planner}


@app.get("/ready")
def ready() -> dict[str, Any]:
    try:
        with httpx.Client(timeout=settings.request_timeout_seconds) as client:
            response = client.get(f"{settings.mcp_sql_url.rstrip('/')}/ready")
            response.raise_for_status()
        mcp = "ok"
    except Exception as exc:
        mcp = f"unavailable: {exc}"
    llm = "configured" if settings.openai_api_key and settings.use_llm_sql_planner else "not_configured_optional"
    return {"status": "ok" if mcp == "ok" else "degraded", "dependencies": {"mcp-sql": mcp, "llm-sql-planner": llm}}


@app.get("/debug/prompts")
def debug_prompts() -> dict[str, Any]:
    names = list_prompts()
    preview = load_prompt("neighborhood/sql_plan_prompt.txt")[:300] if "neighborhood/sql_plan_prompt.txt" in names else None
    return {"prompts": names, "neighborhood_prompt_preview": preview}


def _a2a_error(req: A2ARequest, code: str, message: str, status: str = "error", retryable: bool = False, payload: dict[str, Any] | None = None) -> A2AResponse:
    return A2AResponse(
        trace_id=req.trace_id,
        session_id=req.session_id,
        source_agent="neighborhood-agent",
        target_agent=req.source_agent,
        task_type=req.task_type,
        status=status,  # type: ignore[arg-type]
        payload=payload or {},
        error=ApiError(code=code, message=message, retryable=retryable),
    )


def _execute_query(session_id: str | None, query: dict[str, Any]) -> dict[str, Any]:
    domain_url = {
        "safety": settings.mcp_safety_url,
        "amenity": settings.mcp_amenity_url,
        "entertainment": settings.mcp_entertainment_url,
    }.get(query["domain"], settings.mcp_sql_url)
    args = {
        "purpose": query["purpose"],
        "sql": query["sql"],
        "params": query.get("params", {}),
        "max_rows": 50,
    }
    with httpx.Client(timeout=settings.request_timeout_seconds) as client:
        response = client.post(
            f"{domain_url.rstrip('/')}/tools/execute_readonly_sql",
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
    if not (req.task_type.startswith("neighborhood.") or req.task_type == "area.metrics_query"):
        return _a2a_error(req, "UNSUPPORTED_TASK", f"unsupported neighborhood task: {req.task_type}")

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
            source_agent="neighborhood-agent",
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
            source_agent="neighborhood-agent",
            target_agent=req.source_agent,
            task_type=req.task_type,
            status="unsupported_data_request",
            payload=plan,
            error=None,
        )

    executions: list[dict[str, Any]] = []
    try:
        for query in plan["queries"]:
            result = _execute_query(req.session_id, query)
            executions.append(result)
            if result["status"] == "validation_error":
                return _a2a_error(req, "SQL_VALIDATION_FAILED", (result.get("error") or {}).get("message", "SQL validation failed."), status="validation_failed", retryable=True, payload={"sql_plan": plan, "mcp_result": result})
            if result["status"] == "execution_error":
                return _a2a_error(req, "SQL_EXECUTION_FAILED", "mcp-sql execution failed.", status="dependency_failed", retryable=True, payload={"sql_plan": plan, "mcp_result": result})
    except Exception as exc:
        return _a2a_error(req, "MCP_SQL_UNAVAILABLE", str(exc), status="dependency_failed", retryable=True, payload={"sql_plan": plan})

    summary = summarize_results(req.task_type, plan, executions)
    status = "no_data" if summary.get("status") == "no_data" else "success"
    return A2AResponse(
        trace_id=req.trace_id,
        session_id=req.session_id,
        source_agent="neighborhood-agent",
        target_agent=req.source_agent,
        task_type=req.task_type,
        status=status,  # type: ignore[arg-type]
        payload={"sql_plan": plan, "executions": executions, "neighborhood_result": summary},
        error=None,
    )
