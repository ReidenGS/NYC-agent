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
from app.neighborhood_logic import summarize_results
from nyc_agent_shared.a2a_protocol import (
    build_response_message,
    extract_request_content,
    legacy_a2a_response_to_content,
    request_content_to_legacy_a2a,
)
from nyc_agent_shared.llm_client import LlmClientError, parse_json_object
from nyc_agent_shared.prompt_loader import list_prompts
from nyc_agent_shared.schemas import A2ARequest, A2AResponse, AgentCard, AgentSkill, ApiError

app = FastAPI(title="NYC Agent Neighborhood Agent", version="0.1.0")

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

CREATE TABLE app_area_metrics_daily (
  area_id TEXT NOT NULL,
  metric_date DATE NOT NULL,
  crime_count_30d INTEGER NOT NULL,
  crime_index_100 NUMERIC(6,2) NULL,
  entertainment_poi_count INTEGER NOT NULL,
  convenience_facility_count INTEGER NOT NULL,
  transit_station_count INTEGER NOT NULL,
  complaint_noise_30d INTEGER NOT NULL,
  rent_index_value NUMERIC(10,2) NULL,
  source_snapshot JSONB NOT NULL,
  updated_at TIMESTAMP NOT NULL
);

CREATE TABLE app_crime_incident_snapshot (
  incident_id TEXT PRIMARY KEY,
  area_id TEXT NOT NULL,
  occurred_at TIMESTAMP NULL,
  occurred_date DATE NULL,
  occurred_hour INTEGER NULL,
  borough TEXT NULL,
  offense_category TEXT NULL,
  offense_description TEXT NULL,
  law_category TEXT NULL,
  latitude DOUBLE PRECISION NULL,
  longitude DOUBLE PRECISION NULL,
  geom GEOMETRY(POINT, 4326) NULL,
  source TEXT NOT NULL,
  source_record_id TEXT NOT NULL,
  raw_source JSONB NOT NULL,
  updated_at TIMESTAMP NOT NULL
);

CREATE TABLE app_area_convenience_category_daily (
  area_id TEXT NOT NULL,
  metric_date DATE NOT NULL,
  category_code TEXT NOT NULL,
  category_name TEXT NOT NULL,
  facility_count INTEGER NOT NULL,
  source TEXT NOT NULL,
  source_key TEXT NOT NULL,
  source_value TEXT NOT NULL,
  source_mapping JSONB NOT NULL,
  updated_at TIMESTAMP NOT NULL
);

CREATE TABLE app_area_entertainment_category_daily (
  area_id TEXT NOT NULL,
  metric_date DATE NOT NULL,
  category_code TEXT NOT NULL,
  category_name TEXT NOT NULL,
  poi_count INTEGER NOT NULL,
  source TEXT NOT NULL,
  source_key TEXT NOT NULL,
  source_value TEXT NOT NULL,
  source_mapping JSONB NOT NULL,
  updated_at TIMESTAMP NOT NULL
);

CREATE TABLE app_map_poi_snapshot (
  poi_id TEXT PRIMARY KEY,
  area_id TEXT NOT NULL,
  poi_type TEXT NOT NULL,
  category_code TEXT NOT NULL,
  category_name TEXT NOT NULL,
  name TEXT NULL,
  latitude DOUBLE PRECISION NOT NULL,
  longitude DOUBLE PRECISION NOT NULL,
  geom GEOMETRY(POINT, 4326) NULL,
  intensity NUMERIC(8,4) NOT NULL,
  source TEXT NOT NULL,
  source_key TEXT NULL,
  source_value TEXT NULL,
  source_record_id TEXT NULL,
  source_snapshot JSONB NOT NULL,
  updated_at TIMESTAMP NOT NULL
);
"""

PLAN_PROMPT = ChatPromptTemplate.from_template(
    """
系统提示：你是 Neighborhood SQL 规划器，仅根据给定数据库 schema 生成 SQL 计划 JSON。
- 只输出 JSON，不要额外文本。
- 只能 SELECT；不能 SELECT *；每条 SQL 必须带 LIMIT <= 50。
- 用户输入必须参数化（:param_name）。
- 无法确定必要槽位时返回 clarification_required，不得编造。

数据库 schema:
{database_schema}

SQL few-shot（语义示例）：
- query: Astoria 安全怎么样
  target_table: v_area_metrics_latest
  sql: SELECT v.area_id, d.area_name, v.metric_date, v.crime_count_30d, v.crime_index_100, v.complaint_noise_30d, v.source_snapshot
       FROM v_area_metrics_latest v
       JOIN app_area_dimension d ON d.area_id = v.area_id
       WHERE d.area_name ILIKE :target_area_name
       LIMIT 1
- query: Williamsburg 犯罪情况
  target_table: app_crime_incident_snapshot
  queries:
  - target_table: v_area_metrics_latest
    purpose: analysis
    sql: SELECT v.area_id, v.metric_date, v.crime_count_30d, v.crime_index_100, v.source_snapshot
         FROM v_area_metrics_latest v
         JOIN app_area_dimension d ON d.area_id = v.area_id
         WHERE d.area_name ILIKE :target_area_name
         LIMIT 1
  - target_table: app_crime_incident_snapshot
    purpose: detail
    sql: SELECT c.offense_category, COUNT(*) AS crime_count
       FROM app_crime_incident_snapshot c
       JOIN app_area_dimension d ON d.area_id = c.area_id
       WHERE d.area_name ILIKE :target_area_name
       GROUP BY c.offense_category
       ORDER BY crime_count DESC
       LIMIT 20
- query: LIC 有哪些娱乐设施
  target_table: app_area_entertainment_category_daily
  sql: SELECT e.category_code, e.category_name, e.poi_count, e.metric_date
       FROM app_area_entertainment_category_daily e
       JOIN app_area_dimension d ON d.area_id = e.area_id
       WHERE d.area_name ILIKE :target_area_name
       ORDER BY e.metric_date DESC, e.poi_count DESC
       LIMIT 20

缺槽 few-shot：
- query: 这个区安全吗
  output: {{"status":"clarification_required","missing_slots":["target_area"],"clarification":"请先告诉我你想查询的区域，例如 Astoria 或 Williamsburg。"}}
- query: 看看便利设施
  output: {{"status":"clarification_required","missing_slots":["target_area"],"clarification":"请提供目标区域，我再帮你查便利设施分类。"}}
- query: 比较一下两个区的安全
  output: {{"status":"clarification_required","missing_slots":["comparison_areas"],"clarification":"请提供至少两个要比较的区域名称。"}}

规则补充：
- 每个 query 必须提供 target_table，且 target_table 必须与 SQL 中 FROM/JOIN 的业务主表一致。
- 默认查询数据库中已有的数据，不要根据当前日期自动添加 occurred_date / metric_date 时间过滤。
- 不要把 current_date 转换成默认时间筛选；只有用户明确指定时间范围时，才添加时间过滤。
- crime_count_30d、complaint_noise_30d 等字段表示数据库中已有的预计算窗口指标，不要额外生成当前日期往前推的过滤条件。
- 需要综合区域画像或安全概览时，优先使用 v_area_metrics_latest 并返回 source_snapshot。
- 犯罪查询应优先生成两条 query：analysis 查 v_area_metrics_latest 的 crime_count_30d/crime_index_100；detail 查 app_crime_incident_snapshot 按 offense_category 聚合。
- 用户询问中文犯罪类别时，必须映射到 NYPD offense_category 的实际英文分类，不要只按英文直译做 ILIKE。
  - 偷盗/盗窃/偷窃/theft/larceny：包含 PETIT LARCENY、GRAND LARCENY、OTHER OFFENSES RELATED TO THEFT、GRAND LARCENY OF MOTOR VEHICLE。
  - 抢劫/robbery：包含 ROBBERY。
  - 入室盗窃/burglary：包含 BURGLARY。
  - 攻击/袭击/assault：包含 ASSAULT 3 & RELATED OFFENSES、FELONY ASSAULT。
  - 骚扰/harassment：包含 HARRASSMENT 2。
  - 危险武器/weapons：包含 DANGEROUS WEAPONS。
  - 毒品/drugs：包含 DANGEROUS DRUGS。
  - 交通违法/traffic：包含 VEHICLE AND TRAFFIC LAWS。

域路由（必填）：每条 query 必须显式给出 domain ∈ {{"safety","amenity","entertainment"}}。
- target_table=app_area_metrics_daily / app_crime_incident_snapshot / v_area_metrics_latest → domain="safety"
- target_table=app_area_convenience_category_daily → domain="amenity"
- target_table=app_area_entertainment_category_daily → domain="entertainment"
- target_table=app_map_poi_snapshot：依据 task_type / neighborhood_result_type 选择 amenity 或 entertainment

输出 JSON 结构：
{{
  "status": "sql_ready" | "clarification_required" | "unsupported_data_request",
  "neighborhood_result_type": "safety_summary" | "crime_breakdown" | "amenity_summary" | "amenity_breakdown" | "entertainment_summary" | "entertainment_breakdown" | "area_overview" | "poi_points" | "unsupported_data_request",
  "area_id": string | null,
  "area_name": string | null,
  "queries": [
    {{
      "target_table": string,
      "domain": "safety" | "amenity" | "entertainment",
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


DOMAIN_BY_TARGET_TABLE = {
    "app_area_metrics_daily": "safety",
    "app_crime_incident_snapshot": "safety",
    "v_area_metrics_latest": "safety",
    "app_area_convenience_category_daily": "amenity",
    "app_area_entertainment_category_daily": "entertainment",
}


def resolve_domain(query: dict[str, Any], task_type: str, plan: dict[str, Any]) -> str:
    explicit = (query.get("domain") or "").strip().lower()
    if explicit in {"safety", "amenity", "entertainment"}:
        return explicit
    target_table = (query.get("target_table") or "").strip().lower()
    mapped = DOMAIN_BY_TARGET_TABLE.get(target_table)
    if mapped:
        return mapped
    if target_table == "app_map_poi_snapshot":
        if task_type == "neighborhood.entertainment_query":
            return "entertainment"
        if task_type == "neighborhood.convenience_query":
            return "amenity"
        result_type = (plan.get("neighborhood_result_type") or "").lower()
        if "entertainment" in result_type:
            return "entertainment"
        if "amenity" in result_type or "convenience" in result_type:
            return "amenity"
    raise LlmClientError(f"Unable to resolve MCP domain for target_table={target_table}.")


def validate_plan(plan: dict[str, Any]) -> None:
    status = plan.get("status")
    if status not in {"sql_ready", "clarification_required", "unsupported_data_request"}:
        raise LlmClientError("Neighborhood planner status is invalid.")
    if status != "sql_ready":
        return
    queries = plan.get("queries")
    if not isinstance(queries, list) or not 1 <= len(queries) <= 3:
        raise LlmClientError("Neighborhood SQL plan must include 1-3 queries.")
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
        source_agent="neighborhood-agent",
        target_agent=req.source_agent,
        task_type=req.task_type,
        status=status,  # type: ignore[arg-type]
        payload=payload or {},
        error=ApiError(code=code, message=message, retryable=retryable),
    )


def mcp_url_for(domain: str) -> str:
    if domain == "safety":
        return settings.mcp_safety_url
    if domain == "amenity":
        return settings.mcp_amenity_url
    if domain == "entertainment":
        return settings.mcp_entertainment_url
    raise LlmClientError(f"Unknown MCP domain: {domain}")


def execute_query(session_id: str | None, query: dict[str, Any], *, task_type: str, plan: dict[str, Any]) -> dict[str, Any]:
    domain = resolve_domain(query, task_type, plan)
    args = {
        "target_table": query["target_table"],
        "purpose": query["purpose"],
        "sql": query["sql"],
        "params": query.get("params", {}),
        "max_rows": 50,
    }
    with httpx.Client(timeout=settings.request_timeout_seconds) as client:
        response = client.post(
            f"{mcp_url_for(domain).rstrip('/')}/tools/execute_readonly_sql",
            json={"session_id": session_id, "arguments": args},
        )
        response.raise_for_status()
        result = response.json()
    return {
        "purpose": query["purpose"],
        "expected_result": query.get("expected_result"),
        "domain": domain,
        "status": result.get("status"),
        "data": result.get("data") or [],
        "source_tables": result.get("source_tables") or [],
        "error": result.get("error"),
    }


def _requires_poi_coordinates(task_type: str) -> bool:
    return task_type in {"neighborhood.convenience_query", "neighborhood.entertainment_query"}


def _plan_has_poi_coordinate_detail(plan: dict[str, Any]) -> bool:
    queries = plan.get("queries")
    if not isinstance(queries, list):
        return False
    for query in queries:
        if not isinstance(query, dict):
            continue
        if query.get("purpose") != "detail":
            continue
        target_table = str(query.get("target_table") or "").strip().lower()
        if target_table != "app_map_poi_snapshot":
            continue
        sql = str(query.get("sql") or "").lower()
        if "latitude" in sql and "longitude" in sql:
            return True
    return False


class NeighborhoodQueryServer(A2AServer):
    def __init__(self) -> None:
        super().__init__(
            agent_card=PyAgentCard(
                name="neighborhood-agent",
                description="NYC neighborhood query agent driven by LangChain SQL planning",
                url="http://neighborhood-agent:8012",
                version="1.0.0",
                skills=[PyAgentSkill(name="execute neighborhood query", description="execute neighborhood safety/amenity/entertainment queries")],
                capabilities={"streaming": True, "memory": True},
                default_input_modes=["text"],
                default_output_modes=["text", "data"],
            )
        )
        self.llm = ChatOpenAI(
            model=settings.neighborhood_agent_sql_model,
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
            raise LlmClientError("OPENAI_API_KEY is required for neighborhood SQL planning.")
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
        if not (req.task_type.startswith("neighborhood.") or req.task_type == "area.metrics_query"):
            response = a2a_error(req, "UNSUPPORTED_TASK", f"unsupported neighborhood task: {req.task_type}")
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
                            source_agent="neighborhood-agent",
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
                        response = a2a_error(req, "NEIGHBORHOOD_PLANNER_FAILED", str(exc), status="dependency_failed", retryable=True)
                    break

                if plan["status"] in {"clarification_required", "unsupported_data_request"}:
                    response = A2AResponse(
                        trace_id=req.trace_id,
                        session_id=req.session_id,
                        source_agent="neighborhood-agent",
                        target_agent=req.source_agent,
                        task_type=req.task_type,
                        status=plan["status"],
                        payload=plan,
                        error=None,
                    )
                    break

                if _requires_poi_coordinates(req.task_type) and not _plan_has_poi_coordinate_detail(plan):
                    planner_feedback = (
                        "娱乐/便利查询的 detail SQL 必须查询 app_map_poi_snapshot，"
                        "并在 SELECT 字段中包含 latitude 和 longitude。"
                    )
                    if mcp_retry >= 3:
                        response = A2AResponse(
                            trace_id=req.trace_id,
                            session_id=req.session_id,
                            source_agent="neighborhood-agent",
                            target_agent=req.source_agent,
                            task_type=req.task_type,
                            status="no_data",
                            payload={
                                "status": "no_data",
                                "reason": "poi_coordinate_plan_missing_retry_exhausted",
                                "planner_error": planner_feedback,
                                "sql_plan": plan,
                                "mcp_retry_attempts": mcp_retry,
                            },
                            error=None,
                        )
                        break
                    continue

                executions: list[dict[str, Any]] = []
                try:
                    mcp_validation_error = None
                    for query in plan["queries"]:
                        result = execute_query(req.session_id, query, task_type=req.task_type, plan=plan)
                        executions.append(result)
                        if result["status"] == "validation_error":
                            mcp_validation_error = (result.get("error") or {}).get("message", "SQL validation failed.")
                            planner_feedback = str(mcp_validation_error)
                            break
                        if result["status"] == "execution_error":
                            response = a2a_error(
                                req,
                                "SQL_EXECUTION_FAILED",
                                f"mcp-{result.get('domain', 'neighborhood')} execution failed.",
                                status="dependency_failed",
                                retryable=True,
                                payload={"sql_plan": plan, "mcp_result": result},
                            )
                            break
                    else:
                        summary = summarize_results(req.task_type, plan, executions)
                        status = "no_data" if summary.get("status") == "no_data" else "success"
                        response = A2AResponse(
                            trace_id=req.trace_id,
                            session_id=req.session_id,
                            source_agent="neighborhood-agent",
                            target_agent=req.source_agent,
                            task_type=req.task_type,
                            status=status,  # type: ignore[arg-type]
                            payload={"sql_plan": plan, "executions": executions, "neighborhood_result": summary},
                            error=None,
                        )
                        break

                    if mcp_validation_error is not None:
                        if mcp_retry >= 3:
                            response = A2AResponse(
                                trace_id=req.trace_id,
                                session_id=req.session_id,
                                source_agent="neighborhood-agent",
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
                        "MCP_NEIGHBORHOOD_UNAVAILABLE",  # legacy A2A code; covers safety/amenity/entertainment MCPs
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
                    source_agent="neighborhood-agent",
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
            source_agent="neighborhood-agent",
            target_agent=response_content.get("target_agent"),
            trace_id=response_content.get("trace_id"),
            session_id=response_content.get("session_id"),
            error=response_content.get("error"),
            confidence=response_content.get("confidence"),
            data_quality=response_content.get("data_quality"),
        )


server = NeighborhoodQueryServer()
app = create_flask_app(server)


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "service": "neighborhood-agent", "prompts_loaded": len(list_prompts()), "sql_planner": "llm_required"}


@app.get("/agent.json")
def http_agent_card() -> AgentCard:
    return AgentCard(
        name="Neighborhood Query Assistant",
        description="基于LangChain提供社区安全、便利与娱乐查询服务的助手",
        url="http://neighborhood-agent:8012",
        version="1.0.0",
        skills=[
            AgentSkill(
                id="neighborhood_query",
                name="execute neighborhood query",
                description="执行社区安全、便利、娱乐和综合画像查询",
                task_types=[
                    "neighborhood.crime_query",
                    "neighborhood.convenience_query",
                    "neighborhood.entertainment_query",
                    "area.metrics_query",
                ],
            )
        ],
        capabilities={"streaming": True, "memory": True, "mcp": ["mcp-safety", "mcp-amenity", "mcp-entertainment"]},
    )


@app.get("/ready")
def ready() -> dict[str, Any]:
    deps: dict[str, str] = {}
    for name, url in (
        ("mcp-safety", settings.mcp_safety_url),
        ("mcp-amenity", settings.mcp_amenity_url),
        ("mcp-entertainment", settings.mcp_entertainment_url),
    ):
        try:
            with httpx.Client(timeout=settings.request_timeout_seconds) as client:
                response = client.get(f"{url.rstrip('/')}/ready")
                response.raise_for_status()
            deps[name] = "ok"
        except Exception as exc:
            deps[name] = f"unavailable: {exc}"
    llm = "configured" if settings.openai_api_key and settings.use_llm_sql_planner else "missing_required"
    deps["llm-sql-planner"] = llm
    all_ok = all(v == "ok" for k, v in deps.items() if k != "llm-sql-planner") and llm == "configured"
    return {"status": "ok" if all_ok else "degraded", "dependencies": deps}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8012)
