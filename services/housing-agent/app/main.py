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
from app.housing_logic import summarize_results
from nyc_agent_shared.a2a_protocol import (
    build_response_message,
    extract_request_content,
    legacy_a2a_response_to_content,
    request_content_to_legacy_a2a,
)
from nyc_agent_shared.llm_client import LlmClientError, parse_json_object
from nyc_agent_shared.prompt_loader import list_prompts
from nyc_agent_shared.schemas import A2ARequest, A2AResponse, AgentCard, AgentSkill, ApiError

app = FastAPI(title="NYC Agent Housing Agent", version="0.1.0")

DATABASE_SCHEMA_STRING = """
CREATE TABLE app_area_dimension (
  area_id TEXT PRIMARY KEY,
  area_name TEXT NOT NULL,
  borough TEXT NOT NULL,
  area_type TEXT NULL,
  geom_geojson JSONB NULL,
  geom GEOMETRY(MULTIPOLYGON, 4326) NULL,
  updated_at TIMESTAMP NOT NULL
);

CREATE TABLE app_area_rental_market_daily (
  area_id TEXT NOT NULL,
  metric_date DATE NOT NULL,
  bedroom_type TEXT NOT NULL,
  listing_type TEXT NOT NULL,
  rent_min NUMERIC(10,2) NULL,
  rent_median NUMERIC(10,2) NULL,
  rent_max NUMERIC(10,2) NULL,
  listing_count INTEGER NOT NULL,
  data_quality TEXT NOT NULL,
  source TEXT NOT NULL,
  source_snapshot JSONB NOT NULL,
  updated_at TIMESTAMP NOT NULL
);

CREATE TABLE app_area_rental_listing_snapshot (
  listing_id TEXT PRIMARY KEY,
  area_id TEXT NOT NULL,
  snapshot_date DATE NOT NULL,
  formatted_address TEXT NOT NULL,
  city TEXT NULL,
  state TEXT NULL,
  zip_code TEXT NULL,
  latitude DOUBLE PRECISION NULL,
  longitude DOUBLE PRECISION NULL,
  geom GEOMETRY(POINT, 4326) NULL,
  property_type TEXT NULL,
  bedroom_type TEXT NOT NULL,
  bedrooms NUMERIC(4,1) NULL,
  bathrooms NUMERIC(4,1) NULL,
  square_footage INTEGER NULL,
  monthly_rent NUMERIC(10,2) NULL,
  listing_status TEXT NULL,
  listed_date TIMESTAMP NULL,
  last_seen_date TIMESTAMP NULL,
  days_on_market INTEGER NULL,
  listing_agent_name TEXT NULL,
  listing_agent_phone TEXT NULL,
  source TEXT NOT NULL,
  raw_source JSONB NOT NULL,
  updated_at TIMESTAMP NOT NULL
);

CREATE TABLE app_area_rent_benchmark_monthly (
  area_id TEXT NOT NULL,
  benchmark_month DATE NOT NULL,
  bedroom_type TEXT NOT NULL,
  benchmark_rent NUMERIC(10,2) NULL,
  benchmark_type TEXT NOT NULL,
  benchmark_geo_type TEXT NOT NULL,
  benchmark_geo_id TEXT NOT NULL,
  data_quality TEXT NOT NULL,
  source TEXT NOT NULL,
  source_snapshot JSONB NOT NULL,
  updated_at TIMESTAMP NOT NULL
);
"""

PLAN_PROMPT = ChatPromptTemplate.from_template(
    """
系统提示：你是 Housing SQL 规划器，仅根据给定数据库 schema 生成 SQL 计划 JSON。
- 只输出 JSON，不要额外文本。
- 只能 SELECT；不能 SELECT *；每条 SQL 必须带 LIMIT <= 50。
- 用户输入必须参数化（:param_name）。
- 无法确定必要槽位时返回 clarification_required，不得编造。

数据库 schema:
{database_schema}

SQL few-shot（语义示例）：
- query: Astoria 的 1br 租金中位数
  target_table: app_area_rental_market_daily
  sql: SELECT m.area_id, d.area_name, m.metric_date, m.bedroom_type, m.rent_median, m.listing_count
       FROM app_area_rental_market_daily m
       JOIN app_area_dimension d ON d.area_id = m.area_id
       WHERE d.area_name ILIKE :target_area_name AND m.bedroom_type = :bedroom_type
       ORDER BY m.metric_date DESC
       LIMIT 20
- query: LIC 预算 3000 的活跃房源
  target_table: app_area_rental_listing_snapshot
  sql: SELECT l.listing_id, l.formatted_address, l.bedroom_type, l.monthly_rent, l.latitude, l.longitude, l.listing_status, l.last_seen_date
       FROM app_area_rental_listing_snapshot l
       JOIN app_area_dimension d ON d.area_id = l.area_id
       WHERE d.area_name ILIKE :target_area_name
         AND l.monthly_rent <= :budget_monthly
         AND (l.listing_status ILIKE 'active' OR l.listing_status IS NULL)
       ORDER BY l.monthly_rent ASC, l.last_seen_date DESC
       LIMIT 20
- query: Astoria 和 Williamsburg 的租金对比
  target_table: app_area_rental_market_daily
  sql: SELECT d.area_name, m.metric_date, m.bedroom_type, m.rent_median, m.listing_count
       FROM app_area_rental_market_daily m
       JOIN app_area_dimension d ON d.area_id = m.area_id
       WHERE d.area_name ILIKE ANY(:comparison_area_names)
       ORDER BY m.metric_date DESC
       LIMIT 50

缺槽 few-shot：
- query: 房租怎么样
  output: {{"status":"clarification_required","missing_slots":["target_area","bedroom_type"],"clarification":"请告诉我要查询的区域和户型，例如 Astoria 的 1br。"}}
- query: 帮我找房源
  output: {{"status":"clarification_required","missing_slots":["target_area","budget_monthly"],"clarification":"请告诉我目标区域和预算上限，例如 LIC，预算 3000。"}}
- query: 预算 2500 的房子
  output: {{"status":"clarification_required","missing_slots":["target_area"],"clarification":"请补充你想查询的区域，例如 Astoria 或 Long Island City。"}}

规则补充：
- 每个 query 必须提供 target_table，且 target_table 必须与 SQL 中 FROM/JOIN 的业务主表一致。
- 仅允许 housing 相关表：app_area_rental_market_daily、app_area_rental_listing_snapshot、app_area_rent_benchmark_monthly（可 JOIN app_area_dimension）。

输出 JSON 结构：
{{
  "status": "sql_ready" | "clarification_required" | "unsupported_data_request",
  "housing_result_type": "rent_range" | "budget_fit" | "rent_comparison" | "listing_candidates" | "market_freshness" | "unsupported_data_request",
  "area_id": string | null,
  "area_name": string | null,
  "bedroom_type": string | null,
  "budget_monthly": number | null,
  "queries": [
    {{
      "target_table": string,
      "purpose": "analysis" | "detail" | "fallback",
      "execute_when": string,
      "expected_result": string,
      "sql": string,
      "params": object
    }}
  ],
  "missing_slots": [string],
  "clarification": string,
  "unsupported_reason": string,
  "missing_or_unavailable_fields": [string],
  "suggested_alternative": string,
  "default_applied": [string],
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
    if status not in {"sql_ready", "clarification_required", "unsupported_data_request"}:
        raise LlmClientError("Housing planner status is invalid.")
    if status != "sql_ready":
        return
    queries = plan.get("queries")
    if not isinstance(queries, list) or not 1 <= len(queries) <= 3:
        raise LlmClientError("Housing SQL plan must include 1-3 queries.")
    for query in queries:
        if not isinstance(query, dict):
            raise LlmClientError("Each query must be an object.")
        target_table = str(query.get("target_table") or "").strip()
        if not target_table:
            raise LlmClientError("Query target_table is required.")
        if query.get("purpose") not in {"analysis", "detail", "fallback"}:
            raise LlmClientError("Query purpose is invalid.")
        sql = str(query.get("sql") or "").strip()
        if not sql:
            raise LlmClientError("Query SQL is required.")
        if "select *" in sql.lower():
            raise LlmClientError("LLM generated SELECT *.")
        if "limit" not in sql.lower():
            raise LlmClientError("LLM query missing LIMIT.")
        lowered = sql.lower()
        if (
            "app_area_rental_listing_snapshot" in lowered
            and ("latitude" not in lowered or "longitude" not in lowered)
        ):
            raise LlmClientError("Listing query missing latitude/longitude required for map markers.")
        if not isinstance(query.get("params", {}), dict):
            raise LlmClientError("Query params must be an object.")


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
        source_agent="housing-agent",
        target_agent=req.source_agent,
        task_type=req.task_type,
        status=status,  # type: ignore[arg-type]
        payload=payload or {},
        error=ApiError(code=code, message=message, retryable=retryable),
    )


def execute_query(session_id: str | None, query: dict[str, Any]) -> dict[str, Any]:
    args = {
        "target_table": query["target_table"],
        "purpose": query["purpose"],
        "sql": query["sql"],
        "params": query.get("params", {}),
        "max_rows": 50,
    }
    with httpx.Client(timeout=settings.request_timeout_seconds) as client:
        response = client.post(
            f"{settings.mcp_housing_url.rstrip('/')}/tools/execute_readonly_sql",
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


class HousingQueryServer(A2AServer):
    def __init__(self) -> None:
        super().__init__(
            agent_card=PyAgentCard(
                name="housing-agent",
                description="NYC housing query agent driven by LangChain SQL planning",
                url="http://housing-agent:8011",
                version="1.0.0",
                skills=[PyAgentSkill(name="execute housing query", description="execute housing rent and listing queries")],
                capabilities={"streaming": True, "memory": True},
                default_input_modes=["text"],
                default_output_modes=["text", "data"],
            )
        )
        self.llm = ChatOpenAI(
            model=settings.housing_agent_sql_model,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            timeout=settings.llm_request_timeout_seconds,
            temperature=0,
            model_kwargs={"response_format": {"type": "json_object"}},
        )
        self.chain = PLAN_PROMPT | self.llm

    def generate_sql_plan(
        self, *, task_type: str, query: str, slots: dict[str, Any], domain_context: dict[str, Any]
    ) -> dict[str, Any]:
        if not settings.use_llm_sql_planner:
            raise LlmClientError("USE_LLM_SQL_PLANNER is disabled.")
        if not settings.openai_api_key:
            raise LlmClientError("OPENAI_API_KEY is required for housing SQL planning.")
        current_date = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
        last_error = ""
        for attempt in range(1, 4):
            query_with_feedback = query
            if last_error:
                query_with_feedback = (
                    f"{query}\n\n"
                    f"[上一轮 SQL 校验失败原因]\n{last_error}\n"
                    "请修复以上问题后，重新输出完整 JSON SQL 计划。"
                )
            output = self.chain.invoke(
                {
                    "database_schema": DATABASE_SCHEMA_STRING,
                    "current_date": current_date,
                    "task_type": task_type,
                    "query": query_with_feedback,
                    "slots_json": json.dumps(slots, ensure_ascii=False),
                    "domain_context_json": json.dumps(domain_context, ensure_ascii=False),
                }
            ).content
            text = output if isinstance(output, str) else str(output)
            try:
                plan = parse_json_object(text)
                validate_plan(plan)
            except Exception as exc:  # validation/parse failure -> feedback loop
                last_error = str(exc)
                continue
            plan["planner_mode"] = "llm"
            plan["planner_attempt"] = attempt
            return plan
        raise LlmClientError(f"SQL_PLAN_RETRY_EXHAUSTED: {last_error or 'unknown validation error'}")

    def handle_message(self, message):
        content = extract_request_content(message)
        req = request_content_to_legacy_a2a(content)
        if not req.task_type.startswith("housing."):
            response = a2a_error(req, "UNSUPPORTED_TASK", f"unsupported housing task: {req.task_type}")
        else:
            payload = req.payload
            base_query = str(payload.get("domain_user_query") or "")
            slots = payload.get("slots") or {}
            domain_context = payload.get("domain_context") or {}
            planner_feedback = ""
            response = None

            for mcp_retry in range(1, 4):
                query_for_planner = base_query
                if planner_feedback:
                    query_for_planner = (
                        f"{base_query}\n\n"
                        f"[MCP SQL 校验器返回的错误]\n{planner_feedback}\n"
                        "请根据以上错误重写 SQL，严格遵守白名单和 LIMIT 规则。"
                    )
                try:
                    plan = self.generate_sql_plan(
                        task_type=req.task_type,
                        query=query_for_planner,
                        slots=slots,
                        domain_context=domain_context,
                    )
                except Exception as exc:
                    if "SQL_PLAN_RETRY_EXHAUSTED" in str(exc):
                        response = A2AResponse(
                            trace_id=req.trace_id,
                            session_id=req.session_id,
                            source_agent="housing-agent",
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
                        response = a2a_error(req, "HOUSING_PLANNER_FAILED", str(exc), status="dependency_failed", retryable=True)
                    break

                if plan["status"] in {"clarification_required", "unsupported_data_request"}:
                    response = A2AResponse(
                        trace_id=req.trace_id,
                        session_id=req.session_id,
                        source_agent="housing-agent",
                        target_agent=req.source_agent,
                        task_type=req.task_type,
                        status=plan["status"],
                        payload=plan,
                        error=None,
                    )
                    break

                executions: list[dict[str, Any]] = []
                try:
                    mcp_validation_error = None
                    for query in plan["queries"]:
                        result = execute_query(req.session_id, query)
                        executions.append(result)
                        if result["status"] == "validation_error":
                            mcp_validation_error = (result.get("error") or {}).get("message", "SQL validation failed.")
                            planner_feedback = str(mcp_validation_error)
                            break
                        if result["status"] == "execution_error":
                            response = a2a_error(
                                req,
                                "SQL_EXECUTION_FAILED",
                                "mcp-housing execution failed.",
                                status="dependency_failed",
                                retryable=True,
                                payload={"sql_plan": plan, "mcp_result": result},
                            )
                            break
                    else:
                        summary = summarize_results(plan, executions)
                        status = "no_data" if summary.get("status") == "no_data" else "success"
                        response = A2AResponse(
                            trace_id=req.trace_id,
                            session_id=req.session_id,
                            source_agent="housing-agent",
                            target_agent=req.source_agent,
                            task_type=req.task_type,
                            status=status,  # type: ignore[arg-type]
                            payload={"sql_plan": plan, "executions": executions, "housing_result": summary},
                            error=None,
                        )
                        break

                    if mcp_validation_error is not None:
                        if mcp_retry >= 3:
                            response = A2AResponse(
                                trace_id=req.trace_id,
                                session_id=req.session_id,
                                source_agent="housing-agent",
                                target_agent=req.source_agent,
                                task_type=req.task_type,
                                status="no_data",
                                payload={
                                    "status": "no_data",
                                    "reason": "mcp_sql_validation_retry_exhausted",
                                    "planner_error": str(mcp_validation_error),
                                    "sql_plan": plan,
                                    "executions": executions,
                                    "mcp_retry_attempts": mcp_retry,
                                },
                                error=None,
                            )
                            break
                        continue

                    if response is not None:
                        break
                except Exception as exc:
                    response = a2a_error(
                        req,
                        "MCP_HOUSING_UNAVAILABLE",
                        str(exc),
                        status="dependency_failed",
                        retryable=True,
                        payload={"sql_plan": plan},
                    )
                    break

            if response is None:
                response = A2AResponse(
                    trace_id=req.trace_id,
                    session_id=req.session_id,
                    source_agent="housing-agent",
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
            source_agent="housing-agent",
            target_agent=response_content.get("target_agent"),
            trace_id=response_content.get("trace_id"),
            session_id=response_content.get("session_id"),
            error=response_content.get("error"),
            confidence=response_content.get("confidence"),
            data_quality=response_content.get("data_quality"),
        )


server = HousingQueryServer()
app = create_flask_app(server)


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "service": "housing-agent", "prompts_loaded": len(list_prompts()), "sql_planner": "llm_required"}


@app.get("/agent.json")
def http_agent_card() -> AgentCard:
    return AgentCard(
        name="Housing Query Assistant",
        description="基于LangChain提供租房与房源查询服务的助手",
        url="http://housing-agent:8011",
        version="1.0.0",
        skills=[
            AgentSkill(
                id="housing_query",
                name="execute housing query",
                description="执行租金区间、预算匹配和房源候选查询",
                task_types=["housing.rent_query", "housing.listing_search"],
            )
        ],
        capabilities={"streaming": True, "memory": True, "mcp": ["mcp-housing"]},
    )


@app.get("/ready")
def ready() -> dict[str, Any]:
    try:
        with httpx.Client(timeout=settings.request_timeout_seconds) as client:
            response = client.get(f"{settings.mcp_housing_url.rstrip('/')}/ready")
            response.raise_for_status()
        mcp = "ok"
    except Exception as exc:
        mcp = f"unavailable: {exc}"
    llm = "configured" if settings.openai_api_key and settings.use_llm_sql_planner else "missing_required"
    status = "ok" if mcp == "ok" and llm == "configured" else "degraded"
    return {"status": status, "dependencies": {"mcp-housing": mcp, "llm-sql-planner": llm}}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8011)
