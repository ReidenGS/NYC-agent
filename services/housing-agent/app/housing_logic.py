from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class QuerySpec:
    purpose: str
    expected_result: str
    execute_when: str
    sql: str
    params: dict[str, Any]


def get_slot(slots: dict[str, Any], key: str) -> Any:
    value = slots.get(key)
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    return value


def detect_housing_result_type(task_type: str, query: str, budget: float | None) -> str:
    lower = query.lower()
    if task_type == "housing.listing_search" or any(k in lower for k in ["listing", "apartment", "房源", "公寓", "有哪些房"]):
        return "listing_candidates"
    if budget is not None or any(k in lower for k in ["budget", "预算", "能租", "afford"]):
        return "budget_fit"
    if any(k in lower for k in ["compare", "对比", "差多少", "贵多少"]):
        return "rent_comparison"
    return "rent_range"


def unsupported_reason(query: str) -> str | None:
    unsupported_keywords = {
        "隔音": "当前 schema 没有室内隔音或建筑材料数据。",
        "蟑螂": "当前 schema 没有虫害或室内维护记录数据。",
        "采光": "当前 schema 没有房源采光或窗向数据。",
        "室友": "当前 schema 没有室友可靠性数据。",
        "房东": "当前 schema 没有房东评价数据。",
    }
    for keyword, reason in unsupported_keywords.items():
        if keyword in query:
            return reason
    return None


def build_plan(task_type: str, query: str, slots: dict[str, Any], domain_context: dict[str, Any]) -> dict[str, Any]:
    reason = unsupported_reason(query)
    if reason:
        return {
            "status": "unsupported_data_request",
            "queries": [],
            "unsupported_reason": reason,
            "missing_or_unavailable_fields": ["unsupported_housing_quality_field"],
            "suggested_alternative": "可以改查该区域租金区间、预算匹配或当前可用房源。",
        }

    area_id = get_slot(slots, "area_id") or get_slot(slots, "target_area_id")
    area_name = get_slot(slots, "area_name") or get_slot(slots, "query_area")
    bedroom_type = get_slot(slots, "bedroom_type")
    budget = get_slot(slots, "budget_monthly")
    if budget is not None:
        budget = float(budget)

    result_type = detect_housing_result_type(task_type, query, budget)
    if not area_id:
        return {"status": "clarification_required", "missing_slots": ["target_area"], "clarification": "你想查询哪个纽约区域的租房情况？"}
    if result_type in {"budget_fit", "listing_candidates"} and not bedroom_type:
        return {"status": "clarification_required", "missing_slots": ["bedroom_type"], "clarification": "你想看哪种户型的租金？例如 studio、1b、2b。"}

    listing_limit = int(domain_context.get("listing_limit") or 5)
    listing_limit = max(1, min(listing_limit, 10))

    queries: list[QuerySpec] = []
    if result_type == "rent_range" and not bedroom_type:
        queries.append(QuerySpec(
            purpose="analysis",
            execute_when="always",
            expected_result="rent_overview_by_bedroom",
            sql=(
                "SELECT area_id, bedroom_type, rent_min, rent_median, rent_max, listing_count, metric_date, source, data_quality "
                "FROM app_area_rental_market_daily "
                "WHERE area_id = :area_id AND bedroom_type IN ('studio', '1br', '2br') "
                "ORDER BY metric_date DESC, bedroom_type ASC LIMIT 10"
            ),
            params={"area_id": area_id},
        ))
        queries.append(QuerySpec(
            purpose="fallback",
            execute_when="analysis_no_data",
            expected_result="rent_benchmark_overview_by_bedroom",
            sql=(
                "SELECT area_id, bedroom_type, benchmark_rent, benchmark_type, benchmark_month, data_quality, source "
                "FROM app_area_rent_benchmark_monthly "
                "WHERE area_id = :area_id AND bedroom_type IN ('studio', '1br', '2br') "
                "ORDER BY benchmark_month DESC, bedroom_type ASC LIMIT 10"
            ),
            params={"area_id": area_id},
        ))
    else:
        bedroom_type = bedroom_type or "1br"
        queries.append(QuerySpec(
            purpose="analysis",
            execute_when="always",
            expected_result="rent_range_by_bedroom",
            sql=(
                "SELECT area_id, bedroom_type, rent_min, rent_median, rent_max, listing_count, metric_date, source, data_quality "
                "FROM app_area_rental_market_daily "
                "WHERE area_id = :area_id AND bedroom_type = :bedroom_type "
                "ORDER BY metric_date DESC LIMIT 1"
            ),
            params={"area_id": area_id, "bedroom_type": bedroom_type},
        ))
        if result_type in {"budget_fit", "listing_candidates"}:
            where_budget = " AND monthly_rent <= :budget_monthly" if budget is not None and result_type == "budget_fit" else ""
            params: dict[str, Any] = {"area_id": area_id, "bedroom_type": bedroom_type, "active_status": "active"}
            if budget is not None and result_type == "budget_fit":
                params["budget_monthly"] = budget
            queries.append(QuerySpec(
                purpose="detail",
                execute_when="analysis_has_data_or_listing_requested",
                expected_result="matching_active_listings",
                sql=(
                    "SELECT listing_id, formatted_address, bedroom_type, bedrooms, bathrooms, square_footage, monthly_rent, "
                    "listing_status, listed_date, last_seen_date, days_on_market, source "
                    "FROM app_area_rental_listing_snapshot "
                    f"WHERE area_id = :area_id AND bedroom_type = :bedroom_type AND listing_status = :active_status{where_budget} "
                    f"ORDER BY monthly_rent ASC, last_seen_date DESC LIMIT {listing_limit}"
                ),
                params=params,
            ))
        queries.append(QuerySpec(
            purpose="fallback",
            execute_when="analysis_no_data",
            expected_result="rent_benchmark_by_bedroom",
            sql=(
                "SELECT area_id, bedroom_type, benchmark_rent, benchmark_type, benchmark_month, data_quality, source "
                "FROM app_area_rent_benchmark_monthly "
                "WHERE area_id = :area_id AND bedroom_type = :bedroom_type "
                "ORDER BY benchmark_month DESC LIMIT 1"
            ),
            params={"area_id": area_id, "bedroom_type": bedroom_type},
        ))

    return {
        "status": "sql_ready",
        "housing_result_type": result_type,
        "area_id": area_id,
        "area_name": area_name,
        "bedroom_type": bedroom_type,
        "budget_monthly": budget,
        "queries": [q.__dict__ for q in queries],
        "default_applied": [] if bedroom_type else ["bedroom_overview_studio_1br_2br"],
        "reason_summary": "基于 housing schema 生成只读 SQL 查询计划。",
    }


def summarize_results(plan: dict[str, Any], executions: list[dict[str, Any]]) -> dict[str, Any]:
    result_type = plan.get("housing_result_type")
    analysis = next((r for r in executions if r["purpose"] == "analysis"), None)
    detail = next((r for r in executions if r["purpose"] == "detail"), None)
    fallback = next((r for r in executions if r["purpose"] == "fallback"), None)
    analysis_rows = (analysis or {}).get("data") or []
    detail_rows = (detail or {}).get("data") or []
    fallback_rows = (fallback or {}).get("data") or []

    source_type = "market_daily" if analysis_rows else "benchmark_monthly" if fallback_rows else "none"
    source_rows = analysis_rows or fallback_rows
    if not source_rows and not detail_rows:
        return {
            "status": "no_data",
            "domain": "housing",
            "task_type": "housing.rent_query",
            "housing_result_type": result_type,
            "data_available": False,
            "missing_data_reason": "SQL 查询成功，但当前数据库中没有找到匹配租房数据。",
            "suggested_alternative": "可以改查其他户型、扩大区域，或先运行 rentcast/zori/hud 同步任务。",
            "source_tables": sorted({t for item in executions for t in item.get("source_tables", [])}),
        }

    row = source_rows[0] if source_rows else {}
    budget = plan.get("budget_monthly")
    matching_count = len(detail_rows)
    rent_min = row.get("rent_min")
    rent_median = row.get("rent_median")
    rent_max = row.get("rent_max")
    benchmark_rent = row.get("benchmark_rent")
    budget_fit = None
    reason_code = None
    if result_type == "budget_fit":
        if rent_min is not None and budget is not None and budget < float(rent_min):
            budget_fit, reason_code = "over_budget", "budget_below_market_min"
        elif rent_median is not None and budget is not None and budget >= float(rent_median):
            budget_fit, reason_code = "fit", "budget_above_or_equal_median"
        elif rent_min is not None and budget is not None and float(rent_min) <= budget < float(rent_median or rent_min):
            budget_fit, reason_code = ("partial_fit", "below_median_limited_inventory")
        elif benchmark_rent is not None and budget is not None:
            budget_fit = "partial_fit" if budget >= float(benchmark_rent) else "over_budget"
            reason_code = "benchmark_only"
        else:
            budget_fit, reason_code = "unknown", "insufficient_rent_fields"
        if matching_count >= 5:
            budget_fit, reason_code = "fit", "enough_matching_active_listings"
        elif 1 <= matching_count <= 4 and budget_fit != "fit":
            budget_fit, reason_code = "partial_fit", "some_matching_active_listings"

    return {
        "status": "success",
        "domain": "housing",
        "task_type": "housing.rent_query",
        "housing_result_type": result_type,
        "data_available": True,
        "sql_results": {
            "analysis_rows": len(analysis_rows),
            "detail_rows": len(detail_rows),
            "fallback_rows": len(fallback_rows),
            "executed_queries": [{"purpose": r["purpose"], "status": r["status"], "row_count": len(r.get("data") or [])} for r in executions],
        },
        "derived_metrics": {
            "area_id": plan.get("area_id"),
            "area_name": plan.get("area_name"),
            "bedroom_type": plan.get("bedroom_type"),
            "budget_monthly": budget,
            "rent_min": rent_min,
            "rent_median": rent_median,
            "rent_max": rent_max,
            "benchmark_rent": benchmark_rent,
            "listing_count": row.get("listing_count"),
            "matching_listing_count": matching_count,
            "budget_fit": budget_fit,
            "reason_code": reason_code,
        },
        "data_context": {
            "source_type": source_type,
            "metric_date": row.get("metric_date"),
            "benchmark_month": row.get("benchmark_month"),
            "source": row.get("source"),
            "data_quality": row.get("data_quality") or "reference",
            "benchmark_only": bool(fallback_rows and not analysis_rows),
            "fallback_used": bool(fallback_rows and not analysis_rows),
        },
        "listing_candidates": detail_rows,
        "source_tables": sorted({t for item in executions for t in item.get("source_tables", [])}),
        "default_applied": plan.get("default_applied", []),
    }
