from __future__ import annotations

from typing import Any

from app.config import settings
from app.housing_logic import build_plan as build_deterministic_plan
from nyc_agent_shared.llm_client import JsonLlmClient, LlmClientError
from nyc_agent_shared.prompt_loader import load_prompt

HOUSING_SCHEMA_PROMPT = """
Allowed housing tables and columns:

app_area_rental_market_daily(
  area_id, metric_date, bedroom_type, listing_type,
  rent_min, rent_median, rent_max, listing_count,
  data_quality, source, source_snapshot, updated_at
)

app_area_rental_listing_snapshot(
  listing_id, area_id, snapshot_date, formatted_address,
  city, state, zip_code, latitude, longitude, property_type,
  bedroom_type, bedrooms, bathrooms, square_footage,
  monthly_rent, listing_status, listed_date, last_seen_date,
  days_on_market, source, updated_at
)

app_area_rent_benchmark_monthly(
  area_id, benchmark_month, bedroom_type, benchmark_rent,
  benchmark_type, benchmark_geo_type, benchmark_geo_id,
  data_quality, source, source_snapshot, updated_at
)

app_area_dimension(area_id, area_name, borough, area_type, updated_at)

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


def build_plan(task_type: str, query: str, slots: dict[str, Any], domain_context: dict[str, Any]) -> dict[str, Any]:
    fallback = build_deterministic_plan(task_type, query, slots, domain_context)
    if not settings.use_llm_sql_planner or not settings.openai_api_key:
        fallback["planner_mode"] = "deterministic"
        return fallback

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
        "deterministic_reference_plan": fallback,
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
        sql = str(query.get("sql") or "").strip()
        if not sql:
            raise ValueError("Query SQL is required.")
        if "select *" in sql.lower():
            raise ValueError("LLM generated SELECT *.")
        if "limit" not in sql.lower():
            raise ValueError("LLM query missing LIMIT.")
        if not isinstance(query.get("params", {}), dict):
            raise ValueError("Query params must be an object.")
