from __future__ import annotations

from typing import Any

import httpx
from python_a2a import A2AServer, AgentCard as PyAgentCard, AgentSkill as PyAgentSkill
from python_a2a.server.http import create_flask_app

from app.config import settings
from app.llm_planner import NlToSqlPlanner
from app.mcp_router import execute_query
from app.result_normalizer import summarize_housing_results, summarize_neighborhood_results
from app.skill_loader import TASK_REFERENCE_MAP, load_skill_prompt
from nyc_agent_shared.a2a_protocol import (
    build_response_message,
    extract_request_content,
    legacy_a2a_response_to_content,
    request_content_to_legacy_a2a,
)
from nyc_agent_shared.llm_client import LlmClientError
from nyc_agent_shared.schemas import A2AResponse, AgentCard, AgentSkill, ApiError


MAX_MCP_RETRIES = 3


SUPPORTED_TASKS = set(TASK_REFERENCE_MAP)


def _executions_have_rows(executions: list[dict[str, Any]], purpose: str) -> bool:
    return any(item.get("purpose") == purpose and bool(item.get("data") or []) for item in executions)


def _should_execute(query_spec: dict[str, Any], plan: dict[str, Any], executions: list[dict[str, Any]]) -> bool:
    execute_when = str(query_spec.get("execute_when") or "always")
    if execute_when == "always":
        return True
    if execute_when == "analysis_no_data":
        return not _executions_have_rows(executions, "analysis")
    if execute_when == "detail_no_data":
        return not _executions_have_rows(executions, "detail")
    if execute_when == "analysis_has_data_or_listing_requested":
        return _executions_have_rows(executions, "analysis") or plan.get("housing_result_type") == "listing_candidates"
    return True


def a2a_error(req, code: str, message: str, status: str = "error", retryable: bool = False, payload: dict[str, Any] | None = None) -> A2AResponse:
    return A2AResponse(
        trace_id=req.trace_id,
        session_id=req.session_id,
        source_agent="nl-to-sql-agent",
        target_agent=req.source_agent,
        task_type=req.task_type,
        status=status,  # type: ignore[arg-type]
        payload=payload or {},
        error=ApiError(code=code, message=message, retryable=retryable),
    )


class NlToSqlQueryServer(A2AServer):
    def __init__(self) -> None:
        super().__init__(
            agent_card=PyAgentCard(
                name="nl-to-sql-agent",
                description="NYC NL-to-SQL agent: read-only SQL planning and MCP execution for neighborhood (entertainment / convenience / crime), area metrics, and housing (rent / listing) tasks",
                url="http://nl-to-sql-agent:8016",
                version="1.0.0",
                skills=[
                    PyAgentSkill(
                        name="execute nl-to-sql query",
                        description="generate SQL plans for entertainment / convenience / crime / area_metrics / housing rent / housing listing tasks and execute through mcp-amenity / mcp-entertainment / mcp-housing / mcp-safety",
                    )
                ],
                capabilities={"streaming": False, "memory": False},
                default_input_modes=["text"],
                default_output_modes=["text", "data"],
            )
        )
        self.planner = NlToSqlPlanner()

    def _execute_plan(
        self,
        req,
        plan: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], str | None, A2AResponse | None]:
        """Run every query in the plan.

        Returns (executions, mcp_validation_error, halted_response).
        - executions: rows captured so far (may be partial if halted)
        - mcp_validation_error: message from the first validation_error, or None
        - halted_response: a finalized response when a hard halt (execution_error)
          should short-circuit the outer retry loop, else None.
        """
        executions: list[dict[str, Any]] = []
        for query_spec in plan["queries"]:
            if not _should_execute(query_spec, plan, executions):
                continue
            result = execute_query(req.session_id, req.task_type, query_spec)
            executions.append(result)
            if result["status"] == "validation_error":
                message = (result.get("error") or {}).get("message", "SQL validation failed.")
                return executions, str(message), None
            if result["status"] == "execution_error":
                halted = a2a_error(
                    req,
                    "SQL_EXECUTION_FAILED",
                    "MCP SQL execution failed.",
                    status="dependency_failed",
                    retryable=True,
                    payload={"sql_plan": plan, "mcp_result": result},
                )
                return executions, None, halted
        return executions, None, None

    def _build_summary_response(self, req, plan: dict[str, Any], executions: list[dict[str, Any]]) -> A2AResponse:
        if req.task_type.startswith("housing."):
            summary = summarize_housing_results(req.task_type, plan, executions)
            payload_key = "housing_result"
        else:
            summary = summarize_neighborhood_results(req.task_type, plan, executions)
            payload_key = "neighborhood_result"
        status = "no_data" if summary.get("status") == "no_data" else "success"
        return A2AResponse(
            trace_id=req.trace_id,
            session_id=req.session_id,
            source_agent="nl-to-sql-agent",
            target_agent=req.source_agent,
            task_type=req.task_type,
            status=status,  # type: ignore[arg-type]
            payload={"sql_plan": plan, "executions": executions, payload_key: summary},
            error=None,
        )

    def handle_message(self, message):
        content = extract_request_content(message)
        req = request_content_to_legacy_a2a(content)
        if req.task_type not in SUPPORTED_TASKS:
            response = a2a_error(req, "UNSUPPORTED_TASK", f"unsupported nl-to-sql task: {req.task_type}")
        else:
            payload = req.payload
            base_query = str(payload.get("domain_user_query") or "")
            slots = payload.get("slots") or {}
            domain_context = payload.get("domain_context") or {}
            planner_feedback = ""
            response: A2AResponse | None = None
            plan: dict[str, Any] = {}

            for mcp_retry in range(1, MAX_MCP_RETRIES + 1):
                query_for_planner = base_query
                if planner_feedback:
                    query_for_planner = (
                        f"{base_query}\n\n"
                        f"[MCP SQL 校验器返回的错误]\n{planner_feedback}\n"
                        "请根据以上错误重写 SQL，严格遵守白名单和 LIMIT 规则。"
                    )
                try:
                    plan = self.planner.generate_sql_plan(
                        task_type=req.task_type,
                        query=query_for_planner,
                        slots=slots,
                        domain_context=domain_context,
                    )
                except LlmClientError as exc:
                    if "SQL_PLAN_RETRY_EXHAUSTED" in str(exc):
                        response = A2AResponse(
                            trace_id=req.trace_id,
                            session_id=req.session_id,
                            source_agent="nl-to-sql-agent",
                            target_agent=req.source_agent,
                            task_type=req.task_type,
                            status="no_data",
                            payload={
                                "status": "no_data",
                                "reason": "llm_sql_plan_retry_exhausted",
                                "planner_error": str(exc),
                                "mcp_retry_attempts": mcp_retry,
                            },
                            error=None,
                        )
                    else:
                        response = a2a_error(req, "NL_TO_SQL_PLANNER_FAILED", str(exc), status="dependency_failed", retryable=True)
                    break
                except Exception as exc:
                    response = a2a_error(req, "NL_TO_SQL_PLANNER_FAILED", str(exc), status="dependency_failed", retryable=True)
                    break

                if plan["status"] in {"clarification_required", "unsupported_data_request"}:
                    response = A2AResponse(
                        trace_id=req.trace_id,
                        session_id=req.session_id,
                        source_agent="nl-to-sql-agent",
                        target_agent=req.source_agent,
                        task_type=req.task_type,
                        status=plan["status"],
                        payload=plan,
                        error=None,
                    )
                    break

                try:
                    executions, mcp_validation_error, halted = self._execute_plan(req, plan)
                except Exception as exc:
                    response = a2a_error(
                        req,
                        "MCP_NL_TO_SQL_UNAVAILABLE",
                        str(exc),
                        status="dependency_failed",
                        retryable=True,
                        payload={"sql_plan": plan},
                    )
                    break

                if halted is not None:
                    response = halted
                    break

                if mcp_validation_error is None:
                    response = self._build_summary_response(req, plan, executions)
                    break

                planner_feedback = mcp_validation_error
                if mcp_retry >= MAX_MCP_RETRIES:
                    response = A2AResponse(
                        trace_id=req.trace_id,
                        session_id=req.session_id,
                        source_agent="nl-to-sql-agent",
                        target_agent=req.source_agent,
                        task_type=req.task_type,
                        status="no_data",
                        payload={
                            "status": "no_data",
                            "reason": "mcp_sql_validation_retry_exhausted",
                            "planner_error": mcp_validation_error,
                            "sql_plan": plan,
                            "executions": executions,
                            "mcp_retry_attempts": mcp_retry,
                        },
                        error=None,
                    )
                    break

            if response is None:
                response = A2AResponse(
                    trace_id=req.trace_id,
                    session_id=req.session_id,
                    source_agent="nl-to-sql-agent",
                    target_agent=req.source_agent,
                    task_type=req.task_type,
                    status="no_data",
                    payload={"status": "no_data", "reason": "unknown_planner_exit"},
                    error=None,
                )

        response_content = legacy_a2a_response_to_content(response)
        return build_response_message(
            message,
            task_type=response_content["task_type"],
            status=response_content["status"],
            payload=response_content["payload"],
            source_agent="nl-to-sql-agent",
            target_agent=response_content.get("target_agent"),
            trace_id=response_content.get("trace_id"),
            session_id=response_content.get("session_id"),
            error=response_content.get("error"),
            confidence=response_content.get("confidence"),
            data_quality=response_content.get("data_quality"),
        )


server = NlToSqlQueryServer()
app = create_flask_app(server)


@app.get("/health")
def health() -> dict[str, Any]:
    try:
        load_skill_prompt("neighborhood.entertainment_query")
        skill_status = "loaded"
    except Exception as exc:
        skill_status = f"error: {exc}"
    return {"status": "ok", "service": "nl-to-sql-agent", "skill_status": skill_status}


@app.get("/agent.json")
def http_agent_card() -> AgentCard:
    return AgentCard(
        name="NL-to-SQL Agent",
        description="受控 NL-to-SQL 查询规划与 MCP 执行 agent",
        url="http://nl-to-sql-agent:8016",
        version="1.0.0",
        skills=[
            AgentSkill(
                id="nl_to_sql_query",
                name="execute nl-to-sql query",
                description="执行受支持的 neighborhood / area_metrics / housing 只读 SQL 查询",
                task_types=sorted(SUPPORTED_TASKS),
            )
        ],
        capabilities={"streaming": False, "memory": False, "mcp": ["mcp-amenity", "mcp-entertainment", "mcp-housing", "mcp-safety"]},
    )


@app.get("/ready")
def ready() -> dict[str, Any]:
    deps: dict[str, str] = {}
    for name, url in (
        ("mcp-amenity", settings.mcp_amenity_url),
        ("mcp-entertainment", settings.mcp_entertainment_url),
        ("mcp-housing", settings.mcp_housing_url),
        ("mcp-safety", settings.mcp_safety_url),
    ):
        try:
            with httpx.Client(timeout=settings.request_timeout_seconds) as client:
                response = client.get(f"{url.rstrip('/')}/ready")
                response.raise_for_status()
            deps[name] = "ok"
        except Exception as exc:
            deps[name] = f"unavailable: {exc}"
    try:
        load_skill_prompt("neighborhood.entertainment_query")
        deps["nyc-nl-to-sql-skill"] = "ok"
    except Exception as exc:
        deps["nyc-nl-to-sql-skill"] = f"unavailable: {exc}"
    deps["llm-sql-planner"] = "configured" if settings.openai_api_key and settings.use_llm_sql_planner else "deterministic_fallback"
    all_ok = all(v == "ok" for k, v in deps.items() if k != "llm-sql-planner")
    return {"status": "ok" if all_ok else "degraded", "dependencies": deps}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8016)
