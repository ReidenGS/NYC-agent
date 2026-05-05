from __future__ import annotations

from typing import Any

from app.config import settings
from nyc_agent_shared.llm_client import JsonLlmClient, LlmClientError
from nyc_agent_shared.prompt_loader import load_prompt

HOUSING_SCHEMA_PROMPT = """
你是 Housing SQL 规划器。请只基于以下真实数据库字段生成只读 SQL 计划。

database_schema_string:
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

示例（SQL 语义）：
- query: "Astoria 的 1br 月租中位数"
  sql: SELECT m.area_id, d.area_name, m.metric_date, m.bedroom_type, m.rent_median, m.listing_count, m.source
       FROM app_area_rental_market_daily m
       JOIN app_area_dimension d ON d.area_id = m.area_id
       WHERE d.area_name ILIKE :target_area_name
         AND m.bedroom_type = :bedroom_type
       ORDER BY m.metric_date DESC
       LIMIT 20
- query: "预算 3000 看 LIC 的房源"
  sql: SELECT l.listing_id, l.formatted_address, l.bedroom_type, l.monthly_rent, l.listing_status, l.last_seen_date
       FROM app_area_rental_listing_snapshot l
       JOIN app_area_dimension d ON d.area_id = l.area_id
       WHERE d.area_name ILIKE :target_area_name
         AND l.monthly_rent <= :budget_monthly
         AND (l.listing_status ILIKE 'active' OR l.listing_status IS NULL)
       ORDER BY l.monthly_rent ASC, l.last_seen_date DESC
       LIMIT 20
- query: "Astoria 和 Williamsburg 租金对比"
  sql: SELECT d.area_name, m.metric_date, m.bedroom_type, m.rent_median, m.listing_count
       FROM app_area_rental_market_daily m
       JOIN app_area_dimension d ON d.area_id = m.area_id
       WHERE d.area_name ILIKE ANY(:comparison_area_names)
       ORDER BY m.metric_date DESC
       LIMIT 50

缺槽示例（必须返回 clarification_required）：
- query: "房租怎么样"
  output: {"status":"clarification_required","missing_slots":["target_area","bedroom_type"],"clarification":"请告诉我要查询的区域和户型，例如 Astoria 的 1br。"}
- query: "帮我找房源"
  output: {"status":"clarification_required","missing_slots":["target_area","budget_monthly"],"clarification":"请告诉我目标区域和预算上限，例如 LIC，预算 3000。"}
- query: "预算 2500 的房子"
  output: {"status":"clarification_required","missing_slots":["target_area"],"clarification":"请补充你想查询的区域，例如 Astoria、Long Island City。"}

SQL rules:
- Return SELECT only.
- Never return SELECT *.
- Every query must include LIMIT <= 50.
- Use named params for user-provided values.
- Do not access session/profile/debug/sync tables.
- At most 3 queries.
- purpose must be one of: analysis, detail, fallback.
"""

HOUSING_SQL_PLAN_SCHEMA = """
Return one JSON object:
{
  "status": "sql_ready" | "clarification_required" | "unsupported_data_request",
  "housing_result_type": "rent_range" | "budget_fit" | "rent_comparison" | "listing_candidates" | "market_freshness" | "unsupported_data_request",
  "area_id": string | null,
  "area_name": string | null,
  "bedroom_type": string | null,
  "budget_monthly": number | null,
  "queries": [
    {
      "purpose": "analysis" | "detail" | "fallback",
      "execute_when": string,
      "expected_result": string,
      "sql": string,
      "params": object
    }
  ],
  "missing_slots": [string],
  "clarification": string,
  "unsupported_reason": string,
  "missing_or_unavailable_fields": [string],
  "suggested_alternative": string,
  "default_applied": [string],
  "reason_summary": string
}
"""


def _extract_slot_value(slots: dict[str, Any], key: str):
    raw = slots.get(key)
    if isinstance(raw, dict):
        return raw.get("value")
    return raw


def _deterministic_plan(task_type: str, query: str, slots: dict[str, Any], *, mode: str, reason: str | None = None) -> dict[str, Any]:
    area_id = _extract_slot_value(slots, "area_id")
    area_name = _extract_slot_value(slots, "area_name")
    bedroom_type = _extract_slot_value(slots, "bedroom_type")
    budget_monthly = _extract_slot_value(slots, "budget_monthly")

    missing: list[str] = []
    if not area_id and not area_name:
        missing.append("target_area")
    if "listing_search" in task_type and budget_monthly is None:
        missing.append("budget_monthly")

    if missing:
        plan = {
            "status": "clarification_required",
            "housing_result_type": "listing_candidates" if "listing_search" in task_type else "rent_range",
            "area_id": area_id,
            "area_name": area_name,
            "bedroom_type": bedroom_type,
            "budget_monthly": budget_monthly,
            "queries": [],
            "missing_slots": missing,
            "clarification": "请补充查询所需信息。",
            "unsupported_reason": "",
            "missing_or_unavailable_fields": [],
            "suggested_alternative": "",
            "default_applied": [],
            "reason_summary": "deterministic planner requires essential slots",
            "planner_mode": mode,
        }
        if reason:
            plan["planner_fallback_reason"] = reason
        return plan

    params: dict[str, Any] = {}
    where = []
    if area_id:
        where.append("m.area_id = :area_id")
        params["area_id"] = area_id
    elif area_name:
        where.append("d.area_name ILIKE :target_area_name")
        params["target_area_name"] = str(area_name)
    if bedroom_type:
        where.append("m.bedroom_type = :bedroom_type")
        params["bedroom_type"] = bedroom_type

    if "listing_search" in task_type:
        l_where = []
        l_params: dict[str, Any] = {}
        if area_id:
            l_where.append("l.area_id = :area_id")
            l_params["area_id"] = area_id
        elif area_name:
            l_where.append("d.area_name ILIKE :target_area_name")
            l_params["target_area_name"] = str(area_name)
        if budget_monthly is not None:
            l_where.append("l.monthly_rent <= :budget_monthly")
            l_params["budget_monthly"] = budget_monthly
        sql = (
            "SELECT l.listing_id, l.formatted_address, l.bedroom_type, l.monthly_rent, l.latitude, l.longitude, l.listing_status, l.last_seen_date "
            "FROM app_area_rental_listing_snapshot l "
            "JOIN app_area_dimension d ON d.area_id = l.area_id "
            f"WHERE {' AND '.join(l_where) if l_where else '1=1'} "
            "ORDER BY l.monthly_rent ASC NULLS LAST, l.last_seen_date DESC NULLS LAST "
            "LIMIT 20"
        )
        result_type = "listing_candidates"
        query_payload = {
            "purpose": "analysis",
            "execute_when": "always",
            "expected_result": "candidate listings",
            "sql": sql,
            "params": l_params,
        }
    else:
        sql = (
            "SELECT m.area_id, d.area_name, m.metric_date, m.bedroom_type, m.rent_min, m.rent_median, m.rent_max, m.listing_count "
            "FROM app_area_rental_market_daily m "
            "JOIN app_area_dimension d ON d.area_id = m.area_id "
            f"WHERE {' AND '.join(where) if where else '1=1'} "
            "ORDER BY m.metric_date DESC "
            "LIMIT 20"
        )
        result_type = "rent_range"
        query_payload = {
            "purpose": "analysis",
            "execute_when": "always",
            "expected_result": "rental market summary",
            "sql": sql,
            "params": params,
        }

    plan = {
        "status": "sql_ready",
        "housing_result_type": result_type,
        "area_id": area_id,
        "area_name": area_name,
        "bedroom_type": bedroom_type,
        "budget_monthly": budget_monthly,
        "queries": [query_payload],
        "missing_slots": [],
        "clarification": "",
        "unsupported_reason": "",
        "missing_or_unavailable_fields": [],
        "suggested_alternative": "",
        "default_applied": [],
        "reason_summary": "deterministic housing SQL plan",
        "planner_mode": mode,
    }
    if reason:
        plan["planner_fallback_reason"] = reason
    return plan


def build_plan(task_type: str, query: str, slots: dict[str, Any], domain_context: dict[str, Any]) -> dict[str, Any]:
    if not settings.use_llm_sql_planner:
        return _deterministic_plan(task_type, query, slots, mode="deterministic")
    if not settings.openai_api_key:
        return _deterministic_plan(task_type, query, slots, mode="deterministic")

    prompt = "\n\n".join([
        load_prompt("housing/sql_plan_prompt.txt"),
        HOUSING_SCHEMA_PROMPT,
        HOUSING_SQL_PLAN_SCHEMA,
    ])
    task = {
        "task_type": task_type,
        "domain_user_query": query,
        "slots": slots,
        "domain_context": domain_context,
    }
    try:
        plan = JsonLlmClient(
            api_key=settings.openai_api_key,
            model=settings.housing_agent_sql_model,
            base_url=settings.openai_base_url,
            timeout_seconds=settings.llm_request_timeout_seconds,
        ).generate_json(system_prompt=prompt, user_payload=task)
        validate_plan(plan)
        plan["planner_mode"] = "llm"
        return plan
    except Exception as exc:
        return _deterministic_plan(
            task_type,
            query,
            slots,
            mode="deterministic_fallback",
            reason=str(exc),
        )


def validate_plan(plan: dict[str, Any]) -> None:
    status = plan.get("status")
    if status not in {"sql_ready", "clarification_required", "unsupported_data_request"}:
        raise ValueError("LLM plan status is invalid.")
    if status != "sql_ready":
        return
    queries = plan.get("queries")
    if not isinstance(queries, list) or not 1 <= len(queries) <= 3:
        raise ValueError("LLM SQL plan must include 1-3 queries.")
    for query in queries:
        if not isinstance(query, dict):
            raise ValueError("Each query must be an object.")
        if query.get("purpose") not in {"analysis", "detail", "fallback"}:
            raise ValueError("Query purpose is invalid.")
        sql = str(query.get("sql") or "").strip()
        if not sql:
            raise ValueError("Query SQL is required.")
        if "select *" in sql.lower():
            raise ValueError("LLM generated SELECT *.")
        if "limit" not in sql.lower():
            raise ValueError("LLM query missing LIMIT.")
        lowered = sql.lower()
        if (
            "app_area_rental_listing_snapshot" in lowered
            and ("latitude" not in lowered or "longitude" not in lowered)
        ):
            raise ValueError("Listing query missing latitude/longitude required for map markers.")
        if not isinstance(query.get("params", {}), dict):
            raise ValueError("Query params must be an object.")
