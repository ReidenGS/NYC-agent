from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from app.config import settings
from app.skill_loader import load_skill_prompt
from app.tool_registry import get_mcp_sql_tool, render_mcp_tool_catalog
from nyc_agent_shared.llm_client import LlmClientError, parse_json_object


PLAN_PROMPT = ChatPromptTemplate.from_template(
    """
{skill_prompt}

{mcp_tool_catalog}

Current date: {current_date} (America/New_York)
task_type: {task_type}
query: {query}
slots_json: {slots_json}
domain_context_json: {domain_context_json}
"""
)


def _slot_value(slots: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        raw = slots.get(key)
        if isinstance(raw, dict) and raw.get("value") is not None:
            return raw["value"]
        if raw is not None:
            return raw
    return None


_CRIME_PATTERN_MAP: list[tuple[str, str]] = [
    ("偷", "%LARCENY%"),
    ("盗", "%LARCENY%"),
    ("theft", "%LARCENY%"),
    ("larceny", "%LARCENY%"),
    ("抢劫", "%ROBBERY%"),
    ("robbery", "%ROBBERY%"),
    ("assault", "%ASSAULT%"),
    ("袭击", "%ASSAULT%"),
    ("burglary", "%BURGLARY%"),
    ("入室", "%BURGLARY%"),
]


def _crime_pattern(query: str) -> str | None:
    lower = (query or "").lower()
    for keyword, value in _CRIME_PATTERN_MAP:
        if keyword in lower or keyword in (query or ""):
            return value
    return None


def _safety_unsupported_reason(query: str) -> str | None:
    unsupported = {
        "街灯": "当前 schema 没有街道照明数据。",
        "路灯": "当前 schema 没有街道照明数据。",
        "人多": "当前 schema 没有实时人流或夜间人流数据。",
        "流浪汉": "当前 schema 没有无家可归者分布数据。",
        "某栋楼": "当前 schema 不支持单栋楼安全判断。",
        "邻居": "当前 schema 没有邻里主观评价数据。",
        "吵": "噪音投诉可查，但邻居是否吵无法直接判断。",
    }
    for keyword, message in unsupported.items():
        if keyword in (query or ""):
            return message
    return None


def deterministic_plan(task_type: str, query: str, slots: dict[str, Any], domain_context: dict[str, Any], reason: str | None = None) -> dict[str, Any]:
    area_id = _slot_value(slots, "area_id", "target_area_id")
    area_name = _slot_value(slots, "area_name", "target_area_name", "query_area")
    if task_type.startswith("housing."):
        return deterministic_housing_plan(task_type, query, slots, domain_context, reason=reason)
    if task_type in {"neighborhood.crime_query", "area.metrics_query"}:
        return deterministic_safety_plan(task_type, query, slots, domain_context, reason=reason)
    if not area_id:
        return {
            "status": "clarification_required",
            "neighborhood_result_type": "poi_points",
            "area_id": area_id,
            "area_name": area_name,
            "queries": [],
            "missing_slots": ["target_area"],
            "clarification": "请先告诉我要查询的区域。",
            "unsupported_reason": "",
            "missing_or_unavailable_fields": [],
            "suggested_alternative": "",
            "default_applied": [],
            "reason_summary": "deterministic planner requires target area",
            "planner_mode": "deterministic_fallback" if reason else "deterministic",
            "planner_fallback_reason": reason or "",
        }

    poi_limit = max(1, min(int((domain_context or {}).get("point_limit") or (domain_context or {}).get("result_limit") or 20), 20))
    if task_type == "neighborhood.convenience_query":
        result_type = "amenity_breakdown"
        domain = "amenity"
        mcp_tool = "mcp-amenity.execute_readonly_sql"
        count_expr = "SUM(facility_count) AS poi_count"
        summary_table = "app_area_convenience_category_daily"
        expected_summary = "convenience_count_by_category"
        expected_points = "sample_convenience_points"
        poi_type = "convenience"
    elif task_type == "neighborhood.entertainment_query":
        result_type = "entertainment_breakdown"
        domain = "entertainment"
        mcp_tool = "mcp-entertainment.execute_readonly_sql"
        count_expr = "SUM(poi_count) AS poi_count"
        summary_table = "app_area_entertainment_category_daily"
        expected_summary = "entertainment_count_by_category"
        expected_points = "sample_entertainment_points"
        poi_type = "entertainment"
    else:
        return {
            "status": "unsupported_data_request",
            "neighborhood_result_type": "unsupported_data_request",
            "area_id": area_id,
            "area_name": area_name,
            "queries": [],
            "missing_slots": [],
            "clarification": "",
            "unsupported_reason": f"unsupported nl-to-sql task_type: {task_type}",
            "missing_or_unavailable_fields": [],
            "suggested_alternative": "",
            "default_applied": [],
            "reason_summary": "unsupported task",
        }

    plan = {
        "status": "sql_ready",
        "neighborhood_result_type": result_type,
        "area_id": area_id,
        "area_name": area_name,
        "queries": [
            {
                "mcp_tool": mcp_tool,
                "target_table": summary_table,
                "domain": domain,
                "purpose": "analysis",
                "execute_when": "always",
                "expected_result": expected_summary,
                "sql": (
                    f"SELECT category_code, category_name, {count_expr}, MAX(metric_date) AS metric_date "
                    f"FROM {summary_table} "
                    "WHERE area_id = :area_id GROUP BY category_code, category_name ORDER BY poi_count DESC LIMIT 20"
                ),
                "params": {"area_id": area_id},
            },
            {
                "mcp_tool": mcp_tool,
                "target_table": "app_map_poi_snapshot",
                "domain": domain,
                "purpose": "detail",
                "execute_when": "always",
                "expected_result": expected_points,
                "sql": (
                    "SELECT poi_id, category_code, category_name, name, latitude, longitude, source "
                    "FROM app_map_poi_snapshot "
                    f"WHERE area_id = :area_id AND poi_type = :poi_type ORDER BY category_code ASC, name ASC LIMIT {poi_limit}"
                ),
                "params": {"area_id": area_id, "poi_type": poi_type},
            },
        ],
        "missing_slots": [],
        "clarification": "",
        "unsupported_reason": "",
        "missing_or_unavailable_fields": [],
        "suggested_alternative": "",
        "default_applied": [],
        "reason_summary": "deterministic neighborhood SQL plan",
        "planner_mode": "deterministic_fallback" if reason else "deterministic",
    }
    if reason:
        plan["planner_fallback_reason"] = reason
    return plan


def deterministic_safety_plan(task_type: str, query: str, slots: dict[str, Any], domain_context: dict[str, Any], reason: str | None = None) -> dict[str, Any]:
    area_id = _slot_value(slots, "area_id", "target_area_id")
    area_name = _slot_value(slots, "area_name", "target_area_name", "query_area")
    unsupported = _safety_unsupported_reason(query) if task_type == "neighborhood.crime_query" else None
    if unsupported:
        return {
            "status": "unsupported_data_request",
            "neighborhood_result_type": "unsupported_data_request",
            "area_id": area_id,
            "area_name": area_name,
            "queries": [],
            "missing_slots": [],
            "clarification": "",
            "unsupported_reason": unsupported,
            "missing_or_unavailable_fields": ["unsupported_safety_field"],
            "suggested_alternative": "可以查询整体犯罪统计或区域综合指标。",
            "default_applied": [],
            "reason_summary": "unsupported safety request",
        }
    if not area_id:
        return {
            "status": "clarification_required",
            "neighborhood_result_type": "crime_breakdown" if task_type == "neighborhood.crime_query" else "area_overview",
            "area_id": area_id,
            "area_name": area_name,
            "queries": [],
            "missing_slots": ["target_area"],
            "clarification": "你想查询哪个纽约区域？例如 Astoria、LIC、Williamsburg。",
            "unsupported_reason": "",
            "missing_or_unavailable_fields": [],
            "suggested_alternative": "",
            "default_applied": [],
            "reason_summary": "safety planner requires target area",
            "planner_mode": "deterministic_fallback" if reason else "deterministic",
            "planner_fallback_reason": reason or "",
        }

    mcp_tool = "mcp-safety.execute_readonly_sql"
    queries: list[dict[str, Any]] = []

    if task_type == "neighborhood.crime_query":
        result_type = "crime_breakdown"
        queries.append({
            "mcp_tool": mcp_tool,
            "target_table": "v_area_metrics_latest",
            "domain": "safety",
            "purpose": "analysis",
            "execute_when": "always",
            "expected_result": "safety_metrics_latest",
            "sql": (
                "SELECT area_id, metric_date, crime_count_30d, crime_index_100, source_snapshot "
                "FROM v_area_metrics_latest WHERE area_id = :area_id LIMIT 1"
            ),
            "params": {"area_id": area_id},
        })
        pattern = _crime_pattern(query)
        if pattern:
            queries.append({
                "mcp_tool": mcp_tool,
                "target_table": "app_crime_incident_snapshot",
                "domain": "safety",
                "purpose": "detail",
                "execute_when": "always",
                "expected_result": "crime_count_by_requested_type",
                "sql": (
                    "SELECT offense_category, COUNT(incident_id) AS crime_count "
                    "FROM app_crime_incident_snapshot "
                    "WHERE area_id = :area_id AND offense_category ILIKE :crime_pattern "
                    "GROUP BY offense_category ORDER BY crime_count DESC LIMIT 20"
                ),
                "params": {"area_id": area_id, "crime_pattern": pattern},
            })
        else:
            queries.append({
                "mcp_tool": mcp_tool,
                "target_table": "app_crime_incident_snapshot",
                "domain": "safety",
                "purpose": "detail",
                "execute_when": "always",
                "expected_result": "crime_count_by_category",
                "sql": (
                    "SELECT offense_category, COUNT(incident_id) AS crime_count "
                    "FROM app_crime_incident_snapshot "
                    "WHERE area_id = :area_id "
                    "GROUP BY offense_category ORDER BY crime_count DESC LIMIT 20"
                ),
                "params": {"area_id": area_id},
            })
    else:
        result_type = "area_overview"
        queries.append({
            "mcp_tool": mcp_tool,
            "target_table": "v_area_metrics_latest",
            "domain": "safety",
            "purpose": "analysis",
            "execute_when": "always",
            "expected_result": "area_metrics_latest",
            "sql": (
                "SELECT area_id, metric_date, crime_count_30d, crime_index_100, entertainment_poi_count, "
                "convenience_facility_count, transit_station_count, complaint_noise_30d, source_snapshot "
                "FROM v_area_metrics_latest WHERE area_id = :area_id LIMIT 1"
            ),
            "params": {"area_id": area_id},
        })

    plan = {
        "status": "sql_ready",
        "neighborhood_result_type": result_type,
        "area_id": area_id,
        "area_name": area_name,
        "queries": queries,
        "missing_slots": [],
        "clarification": "",
        "unsupported_reason": "",
        "missing_or_unavailable_fields": [],
        "suggested_alternative": "",
        "default_applied": [],
        "reason_summary": "deterministic safety SQL plan",
        "planner_mode": "deterministic_fallback" if reason else "deterministic",
    }
    if reason:
        plan["planner_fallback_reason"] = reason
    return plan


def _housing_unsupported_reason(query: str) -> str | None:
    unsupported_keywords = {
        "隔音": "当前 schema 没有室内隔音或建筑材料数据。",
        "蟑螂": "当前 schema 没有虫害或室内维护记录数据。",
        "采光": "当前 schema 没有房源采光或窗向数据。",
        "室友": "当前 schema 没有室友可靠性数据。",
        "房东": "当前 schema 没有房东评价数据。",
    }
    for keyword, message in unsupported_keywords.items():
        if keyword in query:
            return message
    lower = query.lower()
    if any(k in lower for k in ["compare", "对比", "差多少", "贵多少", "freshness", "新鲜度", "数据新不新"]):
        return "Phase 2 暂不支持租金对比或数据新鲜度查询。"
    return None


def deterministic_housing_plan(task_type: str, query: str, slots: dict[str, Any], domain_context: dict[str, Any], reason: str | None = None) -> dict[str, Any]:
    area_id = _slot_value(slots, "area_id", "target_area_id")
    area_name = _slot_value(slots, "area_name", "target_area_name", "query_area")
    bedroom_type = _slot_value(slots, "bedroom_type")
    budget = _slot_value(slots, "budget_monthly")
    if budget is not None:
        try:
            budget = float(budget)
        except (TypeError, ValueError):
            budget = None

    unsupported = _housing_unsupported_reason(query)
    if unsupported:
        return {
            "status": "unsupported_data_request",
            "housing_result_type": "unsupported_data_request",
            "area_id": area_id,
            "area_name": area_name,
            "bedroom_type": bedroom_type,
            "budget_monthly": budget,
            "queries": [],
            "missing_slots": [],
            "clarification": "",
            "unsupported_reason": unsupported,
            "missing_or_unavailable_fields": ["unsupported_housing_field"],
            "suggested_alternative": "可以改查该区域租金范围、预算匹配或具体房源列表。",
            "default_applied": [],
            "reason_summary": "unsupported housing request",
        }
    if not area_id:
        return {
            "status": "clarification_required",
            "housing_result_type": "listing_candidates" if task_type == "housing.listing_search" else "rent_range",
            "area_id": area_id,
            "area_name": area_name,
            "bedroom_type": bedroom_type,
            "budget_monthly": budget,
            "queries": [],
            "missing_slots": ["target_area"],
            "clarification": "你想查询哪个纽约区域的租房情况？",
            "unsupported_reason": "",
            "missing_or_unavailable_fields": [],
            "suggested_alternative": "",
            "default_applied": [],
            "reason_summary": "housing planner requires target area",
        }
    if task_type not in {"housing.rent_query", "housing.listing_search"}:
        return {
            "status": "unsupported_data_request",
            "housing_result_type": "unsupported_data_request",
            "area_id": area_id,
            "area_name": area_name,
            "bedroom_type": bedroom_type,
            "budget_monthly": budget,
            "queries": [],
            "missing_slots": [],
            "clarification": "",
            "unsupported_reason": f"unsupported nl-to-sql task_type: {task_type}",
            "missing_or_unavailable_fields": [],
            "suggested_alternative": "",
            "default_applied": [],
            "reason_summary": "unsupported task",
        }

    listing_limit = max(1, min(int((domain_context or {}).get("listing_limit") or 5), 10))
    mcp_tool = "mcp-housing.execute_readonly_sql"
    queries: list[dict[str, Any]] = []
    default_applied: list[str] = []

    if task_type == "housing.listing_search":
        if not bedroom_type:
            return {
                "status": "clarification_required",
                "housing_result_type": "listing_candidates",
                "area_id": area_id,
                "area_name": area_name,
                "bedroom_type": bedroom_type,
                "budget_monthly": budget,
                "queries": [],
                "missing_slots": ["bedroom_type"],
                "clarification": "你想看哪种户型的房源？例如 studio、1b、2b。",
                "unsupported_reason": "",
                "missing_or_unavailable_fields": [],
                "suggested_alternative": "",
                "default_applied": [],
                "reason_summary": "listing search requires bedroom_type",
            }
        budget_filter = " AND monthly_rent <= :budget_monthly" if budget is not None else ""
        params: dict[str, Any] = {"area_id": area_id, "bedroom_type": bedroom_type, "active_status": "active"}
        if budget is not None:
            params["budget_monthly"] = budget
        select_cols = (
            "listing_id, formatted_address, bedroom_type, bedrooms, bathrooms, square_footage, monthly_rent, "
            "latitude, longitude, listing_status, listed_date, last_seen_date, days_on_market, source"
        )
        queries.append({
            "mcp_tool": mcp_tool,
            "target_table": "app_area_rental_listing_snapshot",
            "domain": "housing",
            "purpose": "detail",
            "execute_when": "always",
            "expected_result": "listing_candidates",
            "sql": (
                f"SELECT {select_cols} FROM app_area_rental_listing_snapshot "
                f"WHERE area_id = :area_id AND bedroom_type = :bedroom_type AND listing_status = :active_status{budget_filter} "
                f"ORDER BY monthly_rent ASC, last_seen_date DESC LIMIT {listing_limit}"
            ),
            "params": params,
        })
        fallback_params = {"area_id": area_id, "bedroom_type": bedroom_type}
        if budget is not None:
            fallback_params["budget_monthly"] = budget
        queries.append({
            "mcp_tool": mcp_tool,
            "target_table": "app_area_rental_listing_snapshot",
            "domain": "housing",
            "purpose": "fallback",
            "execute_when": "detail_no_data",
            "expected_result": "recent_seen_listings",
            "sql": (
                f"SELECT {select_cols} FROM app_area_rental_listing_snapshot "
                f"WHERE area_id = :area_id AND bedroom_type = :bedroom_type{budget_filter} "
                f"ORDER BY last_seen_date DESC, monthly_rent ASC NULLS LAST LIMIT {listing_limit}"
            ),
            "params": fallback_params,
        })
        result_type = "listing_candidates"
    else:
        if budget is not None and not bedroom_type:
            return {
                "status": "clarification_required",
                "housing_result_type": "budget_fit",
                "area_id": area_id,
                "area_name": area_name,
                "bedroom_type": bedroom_type,
                "budget_monthly": budget,
                "queries": [],
                "missing_slots": ["bedroom_type"],
                "clarification": "你想看哪种户型的租金？例如 studio、1b、2b。",
                "unsupported_reason": "",
                "missing_or_unavailable_fields": [],
                "suggested_alternative": "",
                "default_applied": [],
                "reason_summary": "budget fit requires bedroom_type",
            }
        result_type = "budget_fit" if budget is not None else "rent_range"
        if not bedroom_type:
            default_applied.append("bedroom_overview_studio_1br_2br")
            queries.append({
                "mcp_tool": mcp_tool,
                "target_table": "app_area_rental_market_daily",
                "domain": "housing",
                "purpose": "analysis",
                "execute_when": "always",
                "expected_result": "rent_overview_by_bedroom",
                "sql": (
                    "SELECT area_id, bedroom_type, rent_min, rent_median, rent_max, listing_count, metric_date, source, data_quality "
                    "FROM app_area_rental_market_daily "
                    "WHERE area_id = :area_id AND bedroom_type IN ('studio', '1br', '2br') "
                    "ORDER BY metric_date DESC, bedroom_type ASC LIMIT 10"
                ),
                "params": {"area_id": area_id},
            })
            queries.append({
                "mcp_tool": mcp_tool,
                "target_table": "app_area_rent_benchmark_monthly",
                "domain": "housing",
                "purpose": "fallback",
                "execute_when": "analysis_no_data",
                "expected_result": "rent_benchmark_overview_by_bedroom",
                "sql": (
                    "SELECT area_id, bedroom_type, benchmark_rent, benchmark_type, benchmark_month, data_quality, source "
                    "FROM app_area_rent_benchmark_monthly "
                    "WHERE area_id = :area_id AND bedroom_type IN ('studio', '1br', '2br') "
                    "ORDER BY benchmark_month DESC, bedroom_type ASC LIMIT 10"
                ),
                "params": {"area_id": area_id},
            })
        else:
            queries.append({
                "mcp_tool": mcp_tool,
                "target_table": "app_area_rental_market_daily",
                "domain": "housing",
                "purpose": "analysis",
                "execute_when": "always",
                "expected_result": "rent_range_by_bedroom",
                "sql": (
                    "SELECT area_id, bedroom_type, rent_min, rent_median, rent_max, listing_count, metric_date, source, data_quality "
                    "FROM app_area_rental_market_daily "
                    "WHERE area_id = :area_id AND bedroom_type = :bedroom_type "
                    "ORDER BY metric_date DESC LIMIT 1"
                ),
                "params": {"area_id": area_id, "bedroom_type": bedroom_type},
            })
            if budget is not None:
                queries.append({
                    "mcp_tool": mcp_tool,
                    "target_table": "app_area_rental_listing_snapshot",
                    "domain": "housing",
                    "purpose": "detail",
                    "execute_when": "analysis_has_data_or_listing_requested",
                    "expected_result": "matching_active_listings",
                    "sql": (
                        "SELECT listing_id, formatted_address, bedroom_type, bedrooms, bathrooms, square_footage, monthly_rent, latitude, longitude, "
                        "listing_status, listed_date, last_seen_date, days_on_market, source "
                        "FROM app_area_rental_listing_snapshot "
                        "WHERE area_id = :area_id AND bedroom_type = :bedroom_type AND monthly_rent <= :budget_monthly AND listing_status = :active_status "
                        f"ORDER BY monthly_rent ASC, last_seen_date DESC LIMIT {listing_limit}"
                    ),
                    "params": {"area_id": area_id, "bedroom_type": bedroom_type, "budget_monthly": budget, "active_status": "active"},
                })
            queries.append({
                "mcp_tool": mcp_tool,
                "target_table": "app_area_rent_benchmark_monthly",
                "domain": "housing",
                "purpose": "fallback",
                "execute_when": "analysis_no_data",
                "expected_result": "rent_benchmark_by_bedroom",
                "sql": (
                    "SELECT area_id, bedroom_type, benchmark_rent, benchmark_type, benchmark_month, data_quality, source "
                    "FROM app_area_rent_benchmark_monthly "
                    "WHERE area_id = :area_id AND bedroom_type = :bedroom_type "
                    "ORDER BY benchmark_month DESC LIMIT 1"
                ),
                "params": {"area_id": area_id, "bedroom_type": bedroom_type},
            })

    plan = {
        "status": "sql_ready",
        "housing_result_type": result_type,
        "area_id": area_id,
        "area_name": area_name,
        "bedroom_type": bedroom_type,
        "budget_monthly": budget,
        "queries": queries,
        "missing_slots": [],
        "clarification": "",
        "unsupported_reason": "",
        "missing_or_unavailable_fields": [],
        "suggested_alternative": "",
        "default_applied": default_applied,
        "reason_summary": "deterministic housing SQL plan",
        "planner_mode": "deterministic_fallback" if reason else "deterministic",
    }
    if reason:
        plan["planner_fallback_reason"] = reason
    return plan


def validate_plan(plan: dict[str, Any], task_type: str) -> None:
    status = plan.get("status")
    if status not in {"sql_ready", "clarification_required", "unsupported_data_request"}:
        raise LlmClientError("NL-to-SQL planner status is invalid.")
    if status != "sql_ready":
        return
    queries = plan.get("queries")
    if not isinstance(queries, list) or not 1 <= len(queries) <= 3:
        raise LlmClientError("SQL plan must include 1-3 queries.")
    expected_domains = {
        "neighborhood.entertainment_query": {"entertainment"},
        "neighborhood.convenience_query": {"amenity"},
        "housing.rent_query": {"housing"},
        "housing.listing_search": {"housing"},
        "neighborhood.crime_query": {"safety"},
        "area.metrics_query": {"safety"},
    }.get(task_type)
    if expected_domains is None:
        raise LlmClientError("Unsupported task_type for NL-to-SQL planner.")
    has_coordinate_detail = False
    has_listing_coordinates = task_type != "housing.listing_search"
    for query in queries:
        if not isinstance(query, dict):
            raise LlmClientError("Each query must be an object.")
        mcp_tool = str(query.get("mcp_tool") or "").strip()
        if not mcp_tool:
            raise LlmClientError("Query mcp_tool is required.")
        try:
            tool = get_mcp_sql_tool(mcp_tool)
        except ValueError as exc:
            raise LlmClientError(str(exc)) from exc
        query_domain = str(query.get("domain") or "").lower()
        if query_domain not in expected_domains:
            raise LlmClientError("Query domain does not match task_type.")
        if query_domain not in tool.domains:
            raise LlmClientError("Query domain is not allowed for selected mcp_tool.")
        if query.get("purpose") not in {"analysis", "detail", "fallback"}:
            raise LlmClientError("Query purpose is invalid.")
        target_table = str(query.get("target_table") or "").strip().lower()
        if not target_table:
            raise LlmClientError("Query target_table is required.")
        if target_table not in tool.target_tables:
            raise LlmClientError("Query target_table is not allowed for selected mcp_tool.")
        sql = str(query.get("sql") or "").strip()
        if not sql:
            raise LlmClientError("Query SQL is required.")
        if "select *" in sql.lower():
            raise LlmClientError("LLM generated SELECT *.")
        if "limit" not in sql.lower():
            raise LlmClientError("LLM query missing LIMIT.")
        if not isinstance(query.get("params", {}), dict):
            raise LlmClientError("Query params must be an object.")
        if query.get("purpose") == "detail" and target_table == "app_map_poi_snapshot":
            lowered = sql.lower()
            has_coordinate_detail = "latitude" in lowered and "longitude" in lowered
        if task_type == "housing.listing_search" and query.get("purpose") == "detail" and target_table == "app_area_rental_listing_snapshot":
            lowered = sql.lower()
            has_listing_coordinates = "latitude" in lowered and "longitude" in lowered
            for forbidden in ("listing_agent_name", "listing_agent_phone", "raw_source", "geom"):
                if forbidden in lowered:
                    raise LlmClientError(f"Listing query must not select {forbidden}.")
    if task_type in {"neighborhood.entertainment_query", "neighborhood.convenience_query"} and not has_coordinate_detail:
        raise LlmClientError("POI detail query must select latitude and longitude from app_map_poi_snapshot.")
    if task_type == "housing.listing_search" and not has_listing_coordinates:
        raise LlmClientError("Listing detail query must select latitude and longitude from app_area_rental_listing_snapshot.")


class NlToSqlPlanner:
    def __init__(self) -> None:
        self.llm = ChatOpenAI(
            model=settings.nl_to_sql_agent_model,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            timeout=settings.llm_request_timeout_seconds,
            temperature=0,
            model_kwargs={"response_format": {"type": "json_object"}},
        )
        self.chain = PLAN_PROMPT | self.llm

    def generate_sql_plan(self, *, task_type: str, query: str, slots: dict[str, Any], domain_context: dict[str, Any]) -> dict[str, Any]:
        if not settings.use_llm_sql_planner or not settings.openai_api_key:
            return deterministic_plan(task_type, query, slots, domain_context)
        current_date = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
        last_error = ""
        for attempt in range(1, 4):
            query_with_feedback = query
            if last_error:
                query_with_feedback = (
                    f"{query}\n\n"
                    f"[上一轮 SQL 计划校验失败原因]\n{last_error}\n"
                    "请修复以上问题后，重新输出完整 JSON SQL 计划。"
                )
            output = self.chain.invoke(
                {
                    "skill_prompt": load_skill_prompt(task_type),
                    "mcp_tool_catalog": render_mcp_tool_catalog(),
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
                validate_plan(plan, task_type)
            except Exception as exc:
                last_error = str(exc)
                continue
            plan["planner_mode"] = "llm"
            plan["planner_attempt"] = attempt
            return plan
        raise LlmClientError(f"SQL_PLAN_RETRY_EXHAUSTED: {last_error or 'unknown validation error'}")
