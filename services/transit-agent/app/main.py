from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from python_a2a import A2AServer, AgentCard as PyAgentCard, AgentSkill as PyAgentSkill
from python_a2a.server.http import create_flask_app

from app.config import settings
from app.transit_rag import TransitCandidate, TransitResolveResult, get_transit_resolver
from nyc_agent_shared.a2a_protocol import (
    build_response_message,
    extract_request_content,
    legacy_a2a_response_to_content,
    request_content_to_legacy_a2a,
)
from nyc_agent_shared.llm_client import LlmClientError, parse_json_object
from nyc_agent_shared.prompt_loader import list_prompts
from nyc_agent_shared.schemas import A2ARequest, A2AResponse, AgentCard, AgentSkill, ApiError

app = FastAPI(title="NYC Agent Transit Agent", version="0.1.0")

TRANSIT_CONTEXT_STRING = """
transit-agent 是实时工具代理，不做静态业务表 SQL 查询。
数据来源：
- mcp-transit.get_next_departures（实时/近实时）
- mcp-transit.get_realtime_commute（实时/近实时）
- mcp-transit.resolve_station_or_stop（站点解析）

缓存策略：
- 允许使用 mcp-transit 内部短缓存结果（realtime cache / fallback cache）。
- 缓存仍视为 transit 工具结果，不是静态离线分析表。
"""

PLAN_PROMPT = ChatPromptTemplate.from_template(
    """
系统提示：你是 Transit Tool 规划器。根据 task_type、query 和 slots 规划 mcp-transit 工具调用步骤。
- 只输出 JSON，不要额外文本。
- 不得编造参数；缺槽必须返回 clarification_required。
- 不生成 SQL，不调用任何非 transit 工具。
- 可使用缓存语义（允许 mcp-transit 返回 cached/fallback）。

上下文:
{transit_context}

few-shot（工具规划）：
- task_type: transit.next_departure
  query: Astoria N 线下一班去 Manhattan
  output: {{"status":"tool_ready","transit_result_type":"next_departure","execution_steps":[{{"tool":"resolve_station_or_stop","arguments":{{"mode":"subway","stop_name":"Astoria"}}}},{{"tool":"get_next_departures","arguments":{{"mode":"subway","route_id":"N","stop_id":"AUTO_FROM_PREV","direction":"Manhattan","limit":2}}}}],"missing_slots":[],"clarification":"","unsupported_reason":"","reason_summary":"查询下一班车"}}
- task_type: transit.realtime_commute
  query: 从 LIC 到 NYU 多久
  output: {{"status":"tool_ready","transit_result_type":"realtime_commute","execution_steps":[{{"tool":"get_realtime_commute","arguments":{{"origin":"Long Island City","destination":"NYU","mode":"either"}}}}],"missing_slots":[],"clarification":"","unsupported_reason":"","reason_summary":"查询实时通勤"}}

缺槽 few-shot：
- task_type: transit.next_departure
  query: 下一班地铁什么时候来
  output: {{"status":"clarification_required","transit_result_type":"next_departure","execution_steps":[],"missing_slots":["mode","route_id","stop_name","direction"],"clarification":"请提供交通方式、线路、站点和方向，例如 N 线 Astoria 往 Manhattan。","unsupported_reason":"","reason_summary":"下一班车缺少关键槽位"}}
- task_type: transit.realtime_commute
  query: 通勤多久
  output: {{"status":"clarification_required","transit_result_type":"realtime_commute","execution_steps":[],"missing_slots":["origin","destination","mode"],"clarification":"请提供出发地、目的地和交通方式。","unsupported_reason":"","reason_summary":"实时通勤缺少关键槽位"}}

输出 JSON 结构：
{{
  "status": "tool_ready" | "clarification_required" | "unsupported_data_request",
  "transit_result_type": "next_departure" | "realtime_commute",
  "execution_steps": [
    {{
      "tool": "resolve_station_or_stop" | "get_next_departures" | "get_realtime_commute",
      "arguments": object
    }}
  ],
  "missing_slots": [string],
  "clarification": string,
  "unsupported_reason": string,
  "reason_summary": string
}}

当前日期: {current_date} (America/New_York)
task_type: {task_type}
query: {query}
slots_json: {slots_json}
domain_context_json: {domain_context_json}
"""
)


def validate_plan(plan: dict[str, Any]) -> None:
    status = plan.get("status")
    if status not in {"tool_ready", "clarification_required", "unsupported_data_request"}:
        raise LlmClientError("Transit planner status is invalid.")
    if plan.get("transit_result_type") not in {"next_departure", "realtime_commute"}:
        raise LlmClientError("Transit result_type is invalid.")
    if status != "tool_ready":
        return
    steps = plan.get("execution_steps")
    if not isinstance(steps, list) or not steps:
        raise LlmClientError("Transit execution_steps must be a non-empty list.")
    allowed = {"resolve_station_or_stop", "get_next_departures", "get_realtime_commute"}
    for step in steps:
        if not isinstance(step, dict):
            raise LlmClientError("Transit step must be an object.")
        if step.get("tool") not in allowed:
            raise LlmClientError("Transit step tool is invalid.")
        if not isinstance(step.get("arguments"), dict):
            raise LlmClientError("Transit step arguments must be an object.")


def a2a_error(
    req: A2ARequest,
    code: str,
    message: str,
    status: str = "error",
    retryable: bool = False,
    payload: dict[str, Any] | None = None,
) -> A2AResponse:
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


def _candidate_to_dict(c: TransitCandidate) -> dict[str, Any]:
    return {
        "kind": c.kind,
        "entity_id": c.entity_id,
        "name": c.name,
        "mode": c.mode,
        "borough": c.borough,
        "latitude": c.latitude,
        "longitude": c.longitude,
        "score": c.score,
    }


def _resolve_to_dict(result: TransitResolveResult) -> dict[str, Any]:
    return {
        "resolved": result.resolved,
        "kind": result.kind,
        "entity_id": result.entity_id,
        "name": result.name,
        "mode": result.mode,
        "borough": result.borough,
        "latitude": result.latitude,
        "longitude": result.longitude,
        "score": result.score,
        "candidates": [_candidate_to_dict(c) for c in (result.candidates or [])],
    }


def handle_resolve_endpoints(req: A2ARequest) -> A2AResponse:
    """RAG endpoint resolver. Payload: {"queries": {"origin":"...","destination":"...","stop_name":"..."}}.

    Each non-empty query string is run through the transit RAG (stop_dimension
    + NTA fusion) and either resolved (kind/entity_id + lat/lon) or returned as
    candidates. Thresholds match orchestrator's NTA RAG so behaviour is uniform.
    """
    payload = req.payload or {}
    queries = payload.get("queries") or {}
    if not isinstance(queries, dict) or not queries:
        return a2a_error(req, "MISSING_REQUIRED_SLOT", "queries map is required", status="validation_failed")

    try:
        resolver = get_transit_resolver()
    except Exception as exc:
        return a2a_error(req, "TRANSIT_RAG_INIT_FAILED", str(exc), status="dependency_failed", retryable=True)

    resolutions: dict[str, Any] = {}
    for key, raw in queries.items():
        text = str(raw or "").strip()
        if not text:
            resolutions[key] = {"resolved": False, "candidates": [], "skipped": True}
            continue
        try:
            result = resolver.resolve(text)
        except Exception as exc:
            return a2a_error(req, "TRANSIT_RAG_FAILED", f"resolve failed for {key}: {exc}", status="dependency_failed", retryable=True)
        resolutions[key] = _resolve_to_dict(result)

    return A2AResponse(
        trace_id=req.trace_id,
        session_id=req.session_id,
        source_agent="transit-agent",
        target_agent=req.source_agent,
        task_type=req.task_type,
        status="success",
        payload={
            "resolutions": resolutions,
            "rag": {
                "method": "transit_vector_rag",
                "doc_count": resolver.doc_count(),
                "thresholds": {
                    "min_similarity": settings.transit_rag_min_similarity,
                    "min_margin": settings.transit_rag_min_margin,
                    "top_k": settings.transit_rag_top_k,
                },
            },
        },
        error=None,
    )


def call_tool(tool: str, session_id: str | None, arguments: dict[str, Any]) -> dict[str, Any]:
    with httpx.Client(timeout=settings.request_timeout_seconds) as client:
        response = client.post(
            f"{settings.mcp_transit_url.rstrip('/')}/tools/{tool}",
            json={"session_id": session_id, "arguments": arguments},
        )
        response.raise_for_status()
        return response.json()


def _slot_value(slots: dict[str, Any], key: str) -> Any:
    value = slots.get(key)
    if isinstance(value, dict) and "value" in value:
        return value.get("value")
    return value


def _resolved_location_name(slots: dict[str, Any], key: str) -> str | None:
    raw = _slot_value(slots, key)
    if isinstance(raw, dict):
        # RAG-resolved shape from orchestrator:
        # {"kind","entity_id","name","latitude","longitude",...}
        name = raw.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


class TransitQueryServer(A2AServer):
    def __init__(self) -> None:
        super().__init__(
            agent_card=PyAgentCard(
                name="transit-agent",
                description="NYC transit query agent driven by LangChain tool planning",
                url="http://transit-agent:8013",
                version="1.0.0",
                skills=[PyAgentSkill(name="execute transit query", description="execute realtime commute and next departure queries")],
                capabilities={"streaming": True, "memory": True},
                default_input_modes=["text"],
                default_output_modes=["text", "data"],
            )
        )
        self.llm = ChatOpenAI(
            model=settings.transit_agent_tool_model,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            timeout=settings.llm_request_timeout_seconds,
            temperature=0,
            model_kwargs={"response_format": {"type": "json_object"}},
        )
        self.chain = PLAN_PROMPT | self.llm

    def generate_tool_plan(
        self, *, task_type: str, query: str, slots: dict[str, Any], domain_context: dict[str, Any]
    ) -> dict[str, Any]:
        if not settings.openai_api_key:
            raise LlmClientError("OPENAI_API_KEY is required for transit tool planning.")
        current_date = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
        output = self.chain.invoke(
            {
                "transit_context": TRANSIT_CONTEXT_STRING,
                "current_date": current_date,
                "task_type": task_type,
                "query": query,
                "slots_json": json.dumps(slots, ensure_ascii=False),
                "domain_context_json": json.dumps(domain_context, ensure_ascii=False),
            }
        ).content
        text = output if isinstance(output, str) else str(output)
        plan = parse_json_object(text)
        validate_plan(plan)
        plan["planner_mode"] = "llm"
        return plan

    def handle_message(self, message):
        content = extract_request_content(message)
        req = request_content_to_legacy_a2a(content)
        if not req.task_type.startswith("transit."):
            response = a2a_error(req, "UNSUPPORTED_TASK", f"unsupported transit task: {req.task_type}")
        elif req.task_type == "transit.resolve_endpoints":
            response = handle_resolve_endpoints(req)
        else:
            slots = req.payload.get("slots") or {}
            try:
                plan = self.generate_tool_plan(
                    task_type=req.task_type,
                    query=str(req.payload.get("domain_user_query") or ""),
                    slots=slots,
                    domain_context=req.payload.get("domain_context") or {},
                )
            except Exception as exc:
                response = a2a_error(req, "TRANSIT_PLANNER_FAILED", str(exc), status="dependency_failed", retryable=True)
            else:
                if plan["status"] in {"clarification_required", "unsupported_data_request"}:
                    response = A2AResponse(
                        trace_id=req.trace_id,
                        session_id=req.session_id,
                        source_agent="transit-agent",
                        target_agent=req.source_agent,
                        task_type=req.task_type,
                        status=plan["status"],
                        payload=plan,
                        error=None,
                    )
                else:
                    try:
                        execution_steps = plan.get("execution_steps") or []
                        resolved_origin = _resolved_location_name(slots, "origin")
                        resolved_destination = _resolved_location_name(slots, "destination")
                        tool_results: list[dict[str, Any]] = []
                        last_success_data: dict[str, Any] = {}
                        for step in execution_steps:
                            tool = str(step.get("tool") or "")
                            args = step.get("arguments") or {}
                            if not isinstance(args, dict):
                                response = a2a_error(req, "TRANSIT_PLANNER_INVALID", "step arguments must be object", status="validation_failed")
                                break
                            if tool == "get_realtime_commute":
                                if resolved_origin:
                                    args["origin"] = resolved_origin
                                if resolved_destination:
                                    args["destination"] = resolved_destination
                            result = call_tool(tool, req.session_id, args)
                            tool_results.append(result)
                            if result.get("status") == "success" and isinstance(result.get("data"), dict):
                                last_success_data = result["data"]
                        else:
                            final = tool_results[-1]
                            status = "success" if final.get("status") == "success" else "no_data"
                            transit_result = {
                                "status": status,
                                "domain": "transit",
                                "task_type": req.task_type,
                                "transit_result_type": plan.get("transit_result_type"),
                                "derived_metrics": final.get("data") or last_success_data,
                                "data_context": {
                                    "realtime_used": bool((final.get("data") or {}).get("realtime_used")),
                                    "fallback_used": bool((final.get("data") or {}).get("fallback_used")),
                                },
                                "display_refs": {"route_layer_id": None},
                            }
                            response = A2AResponse(
                                trace_id=req.trace_id,
                                session_id=req.session_id,
                                source_agent="transit-agent",
                                target_agent=req.source_agent,
                                task_type=req.task_type,
                                status=status,  # type: ignore[arg-type]
                                payload={"tool_plan": plan, "transit_result": transit_result, "tool_results": tool_results},
                                error=None,
                            )
                    except Exception as exc:
                        response = a2a_error(
                            req,
                            "MCP_TRANSIT_UNAVAILABLE",
                            str(exc),
                            status="dependency_failed",
                            retryable=True,
                            payload={"tool_plan": plan},
                        )

        response_content = legacy_a2a_response_to_content(response)
        return build_response_message(
            message,
            task_type=response_content["task_type"],
            status=response_content["status"],
            payload=response_content["payload"],
            source_agent="transit-agent",
            target_agent=response_content.get("target_agent"),
            trace_id=response_content.get("trace_id"),
            session_id=response_content.get("session_id"),
            error=response_content.get("error"),
            confidence=response_content.get("confidence"),
            data_quality=response_content.get("data_quality"),
        )


server = TransitQueryServer()
app = create_flask_app(server)


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "service": "transit-agent", "prompts_loaded": len(list_prompts()), "tool_planner": "llm_required"}


@app.get("/agent.json")
def http_agent_card() -> AgentCard:
    return AgentCard(
        name="Transit Query Assistant",
        description="基于LangChain提供实时通勤和下一班车查询服务的助手",
        url="http://transit-agent:8013",
        version="1.0.0",
        skills=[
            AgentSkill(
                id="transit_query",
                name="execute transit query",
                description="执行实时通勤和下一班车查询，支持缓存降级",
                task_types=["transit.next_departure", "transit.realtime_commute", "transit.commute_time", "transit.resolve_endpoints"],
            )
        ],
        capabilities={"streaming": True, "memory": True, "mcp": ["mcp-transit"]},
    )


@app.get("/ready")
def ready() -> dict[str, Any]:
    try:
        with httpx.Client(timeout=settings.request_timeout_seconds) as client:
            response = client.get(f"{settings.mcp_transit_url.rstrip('/')}/ready")
            response.raise_for_status()
        mcp = "ok"
    except Exception as exc:
        mcp = f"unavailable: {exc}"
    llm = "configured" if settings.openai_api_key else "missing_required"
    status = "ok" if mcp == "ok" and llm == "configured" else "degraded"
    return {"status": status, "dependencies": {"mcp-transit": mcp, "llm-tool-planner": llm}}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8013)
