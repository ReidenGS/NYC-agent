from __future__ import annotations

from typing import Any

from app.config import settings
from app.neighborhood_logic import build_plan as build_deterministic_plan
from nyc_agent_shared.llm_client import JsonLlmClient, LlmClientError
from nyc_agent_shared.prompt_loader import load_prompt

NEIGHBORHOOD_SCHEMA_PROMPT = """
Allowed neighborhood tables and columns by task:

safety:
v_area_metrics_latest(
  area_id, metric_date, crime_count_30d, crime_index_100,
  entertainment_poi_count, convenience_facility_count,
  transit_station_count, complaint_noise_30d, source_snapshot, updated_at
)
app_crime_incident_snapshot(
  incident_id, area_id, occurred_at, occurred_date, occurred_hour,
  borough, offense_category, offense_description, law_category,
  latitude, longitude, source, source_record_id, updated_at
)

amenity:
app_area_convenience_category_daily(
  area_id, metric_date, category_code, category_name,
  facility_count, source, source_key, source_value, source_mapping, updated_at
)
app_map_poi_snapshot(
  poi_id, area_id, poi_type, category_code, category_name,
  name, latitude, longitude, intensity, source, source_key, source_value,
  source_record_id, source_snapshot, updated_at
)

entertainment:
app_area_entertainment_category_daily(
  area_id, metric_date, category_code, category_name,
  poi_count, source, source_key, source_value, source_mapping, updated_at
)
app_map_poi_snapshot(
  poi_id, area_id, poi_type, category_code, category_name,
  name, latitude, longitude, intensity, source, source_key, source_value,
  source_record_id, source_snapshot, updated_at
)

shared:
app_area_dimension(area_id, area_name, borough, area_type, updated_at)

SQL rules:
- Return SELECT only.
- Never return SELECT *.
- Every query must include LIMIT <= 50.
- POI/detail LIMIT <= 20.
- Use named params for user-provided values.
- Do not access session/profile/debug/sync tables.
- At most 3 queries.
- purpose must be one of: analysis, detail, fallback.
- query.domain must be one of: safety, amenity, entertainment.
"""

NEIGHBORHOOD_SQL_PLAN_SCHEMA = """
Return one JSON object:
{
  "status": "sql_ready" | "clarification_required" | "unsupported_data_request",
  "neighborhood_result_type": "safety_summary" | "crime_breakdown" | "amenity_summary" | "amenity_breakdown" | "entertainment_summary" | "entertainment_breakdown" | "area_overview" | "poi_points" | "unsupported_data_request",
  "area_id": string | null,
  "area_name": string | null,
  "queries": [
    {
      "purpose": "analysis" | "detail" | "fallback",
      "execute_when": string,
      "expected_result": string,
      "domain": "safety" | "amenity" | "entertainment",
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


def build_plan(task_type: str, query: str, slots: dict[str, Any], domain_context: dict[str, Any]) -> dict[str, Any]:
    fallback = build_deterministic_plan(task_type, query, slots, domain_context)
    if not settings.use_llm_sql_planner or not settings.openai_api_key:
        fallback["planner_mode"] = "deterministic"
        return fallback

    prompt = "\n\n".join([
        load_prompt("neighborhood/sql_plan_prompt.txt"),
        NEIGHBORHOOD_SCHEMA_PROMPT,
        NEIGHBORHOOD_SQL_PLAN_SCHEMA,
    ])
    task = {
        "task_type": task_type,
        "domain_user_query": query,
        "slots": slots,
        "domain_context": domain_context,
        "deterministic_reference_plan": fallback,
    }
    try:
        plan = JsonLlmClient(
            api_key=settings.openai_api_key,
            model=settings.neighborhood_agent_sql_model,
            base_url=settings.openai_base_url,
            timeout_seconds=settings.llm_request_timeout_seconds,
        ).generate_json(system_prompt=prompt, user_payload=task)
        validate_plan(plan)
        plan["planner_mode"] = "llm"
        return plan
    except (LlmClientError, ValueError) as exc:
        fallback["planner_mode"] = "deterministic_fallback"
        fallback["planner_fallback_reason"] = str(exc)
        return fallback


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
        if query.get("domain") not in {"safety", "amenity", "entertainment"}:
            raise ValueError("Query domain is invalid.")
        sql = str(query.get("sql") or "").strip()
        if not sql:
            raise ValueError("Query SQL is required.")
        if "select *" in sql.lower():
            raise ValueError("LLM generated SELECT *.")
        if "limit" not in sql.lower():
            raise ValueError("LLM query missing LIMIT.")
        if not isinstance(query.get("params", {}), dict):
            raise ValueError("Query params must be an object.")
