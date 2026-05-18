from __future__ import annotations

from typing import Any


def _density_level(total: int) -> str:
    if total >= 50:
        return "high"
    if total >= 15:
        return "medium"
    if total >= 1:
        return "low"
    return "unknown"


def _safety_level(crime_count: int | None, crime_index: float | None) -> str:
    if crime_index is not None:
        if float(crime_index) >= 70:
            return "elevated_risk"
        if float(crime_index) >= 40:
            return "medium_risk"
        return "low_risk"
    if crime_count is None:
        return "unknown"
    if crime_count >= 200:
        return "elevated_risk"
    if crime_count >= 50:
        return "medium_risk"
    return "low_risk"


def summarize_neighborhood_results(task_type: str, plan: dict[str, Any], executions: list[dict[str, Any]]) -> dict[str, Any]:
    analysis = next((r for r in executions if r["purpose"] == "analysis"), None)
    detail = next((r for r in executions if r["purpose"] == "detail"), None)
    analysis_rows = (analysis or {}).get("data") or []
    detail_rows = (detail or {}).get("data") or []
    source_tables = sorted({t for item in executions for t in item.get("source_tables", [])})

    if not analysis_rows and not detail_rows:
        return {
            "status": "no_data",
            "domain": "neighborhood",
            "task_type": task_type,
            "neighborhood_result_type": plan.get("neighborhood_result_type"),
            "data_available": False,
            "missing_data_reason": "SQL 查询成功，但当前数据库中没有找到匹配区域画像数据。",
            "suggested_alternative": "可以扩大查询范围，或先运行对应的数据同步任务。",
            "source_tables": source_tables,
        }

    metrics_row = analysis_rows[0] if analysis_rows else {}
    if task_type == "neighborhood.crime_query":
        total = metrics_row.get("crime_count_30d")
        index = metrics_row.get("crime_index_100")
        derived = {
            "area_id": plan.get("area_id"),
            "area_name": plan.get("area_name"),
            "total_crime_count_30d": total,
            "crime_index_100": index,
            "safety_level": _safety_level(total, index),
            "crime_count_by_category": detail_rows,
        }
        map_layer_ids: list[str] = []
        map_points: list[dict[str, Any]] = []
    elif task_type == "area.metrics_query":
        derived = {
            "area_id": plan.get("area_id"),
            "area_name": plan.get("area_name"),
            "metrics": metrics_row,
        }
        map_layer_ids = []
        map_points = []
    else:
        total = int(sum(int(row.get("poi_count") or 0) for row in analysis_rows))
        derived = {
            "area_id": plan.get("area_id"),
            "area_name": plan.get("area_name"),
            "total_count": total,
            "count_by_category": analysis_rows,
            "top_categories": analysis_rows[:5],
            "poi_density_level": _density_level(total),
            "sample_points": detail_rows[:20],
        }
        map_layer_ids = ["entertainment" if task_type == "neighborhood.entertainment_query" else "amenity"]
        map_points = detail_rows[:20]
    return {
        "status": "success",
        "domain": "neighborhood",
        "task_type": task_type,
        "neighborhood_result_type": plan.get("neighborhood_result_type"),
        "data_available": True,
        "sql_results": [{"purpose": r["purpose"], "status": r["status"], "row_count": len(r.get("data") or [])} for r in executions],
        "derived_metrics": derived,
        "data_context": {
            "metric_date": metrics_row.get("metric_date"),
            "data_quality": "reference",
            "source_snapshot": metrics_row.get("source_snapshot") or {},
            "fallback_used": False,
        },
        "display_refs": {"map_layer_ids": map_layer_ids, "display_result_ids": [], "map_points": map_points},
        "source_tables": source_tables,
        "default_applied": plan.get("default_applied", []),
    }


def summarize_housing_results(task_type: str, plan: dict[str, Any], executions: list[dict[str, Any]]) -> dict[str, Any]:
    result_type = plan.get("housing_result_type")
    analysis = next((r for r in executions if r["purpose"] == "analysis"), None)
    detail = next((r for r in executions if r["purpose"] == "detail"), None)
    fallback = next((r for r in executions if r["purpose"] == "fallback"), None)
    analysis_rows = (analysis or {}).get("data") or []
    detail_rows = (detail or {}).get("data") or []
    fallback_rows = (fallback or {}).get("data") or []
    source_tables = sorted({t for item in executions for t in item.get("source_tables", [])})

    if task_type == "housing.listing_search":
        fallback_used = bool(fallback_rows and not detail_rows)
        candidates = fallback_rows if fallback_used else detail_rows
        if fallback_used:
            candidates = [
                {
                    **row,
                    "availability": "stale_or_unknown",
                    "not_realtime_inventory": True,
                    "data_quality": "reference",
                    "fallback_used": True,
                }
                for row in candidates
            ]
        if not candidates:
            return {
                "status": "no_data",
                "domain": "housing",
                "task_type": task_type,
                "housing_result_type": "listing_candidates",
                "data_available": False,
                "missing_data_reason": "SQL 查询成功，但当前数据库中没有找到匹配房源。",
                "suggested_alternative": "可以放宽预算、换户型，或扩大区域。",
                "source_tables": source_tables,
                "listing_candidates": [],
            }
        return {
            "status": "success",
            "domain": "housing",
            "task_type": task_type,
            "housing_result_type": "listing_candidates",
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
                "budget_monthly": plan.get("budget_monthly"),
                "matching_listing_count": len(candidates),
            },
            "data_context": {
                "source_type": "listing_snapshot",
                "not_realtime_inventory": fallback_used,
                "fallback_used": fallback_used,
                "data_quality": "reference",
            },
            "listing_candidates": candidates,
            "source_tables": source_tables,
            "default_applied": plan.get("default_applied", []),
        }

    source_type = "market_daily" if analysis_rows else "benchmark_monthly" if fallback_rows else "none"
    source_rows = analysis_rows or fallback_rows
    if not source_rows and not detail_rows:
        return {
            "status": "no_data",
            "domain": "housing",
            "task_type": task_type,
            "housing_result_type": result_type,
            "data_available": False,
            "missing_data_reason": "SQL 查询成功，但当前数据库中没有找到匹配租房数据。",
            "suggested_alternative": "可以改查其他户型、扩大区域，或先运行 rentcast/zori/hud 同步任务。",
            "source_tables": source_tables,
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
            budget_fit, reason_code = "partial_fit", "below_median_limited_inventory"
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
        "task_type": task_type,
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
        "source_tables": source_tables,
        "default_applied": plan.get("default_applied", []),
    }
