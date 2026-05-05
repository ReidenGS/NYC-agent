from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class QuerySpec:
    purpose: str
    expected_result: str
    execute_when: str
    domain: str
    sql: str
    params: dict[str, Any]


def get_slot(slots: dict[str, Any], key: str) -> Any:
    value = slots.get(key)
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    return value


def unsupported_reason(query: str) -> str | None:
    unsupported = {
        "街灯": "当前 schema 没有街道照明数据。",
        "路灯": "当前 schema 没有街道照明数据。",
        "人多": "当前 schema 没有实时人流或夜间人流数据。",
        "流浪汉": "当前 schema 没有无家可归者分布数据。",
        "某栋楼": "当前 schema 不支持单栋楼安全判断。",
        "邻居": "当前 schema 没有邻里主观评价数据。",
        "吵": "噪音投诉可查，但邻居是否吵无法直接判断。",
    }
    for keyword, reason in unsupported.items():
        if keyword in query:
            return reason
    return None


def crime_pattern(query: str) -> str | None:
    lower = query.lower()
    mapping = {
        "偷": "%LARCENY%",
        "盗": "%LARCENY%",
        "theft": "%LARCENY%",
        "larceny": "%LARCENY%",
        "抢劫": "%ROBBERY%",
        "robbery": "%ROBBERY%",
        "assault": "%ASSAULT%",
        "袭击": "%ASSAULT%",
        "burglary": "%BURGLARY%",
        "入室": "%BURGLARY%",
    }
    for key, value in mapping.items():
        if key in lower or key in query:
            return value
    return None


def infer_result_type(task_type: str) -> tuple[str, str]:
    if task_type == "neighborhood.crime_query":
        return "safety", "crime_breakdown"
    if task_type == "neighborhood.convenience_query":
        return "amenity", "amenity_breakdown"
    if task_type == "neighborhood.entertainment_query":
        return "entertainment", "entertainment_breakdown"
    return "safety", "area_overview"


def build_plan(task_type: str, query: str, slots: dict[str, Any], domain_context: dict[str, Any]) -> dict[str, Any]:
    reason = unsupported_reason(query)
    if reason:
        return {
            "status": "unsupported_data_request",
            "queries": [],
            "unsupported_reason": reason,
            "missing_or_unavailable_fields": ["unsupported_neighborhood_field"],
            "suggested_alternative": "可以改查犯罪统计、便利设施分类、娱乐设施分类或地图点位。",
        }

    area_id = get_slot(slots, "area_id") or get_slot(slots, "target_area_id")
    area_name = get_slot(slots, "area_name") or get_slot(slots, "query_area")
    if not area_id:
        return {"status": "clarification_required", "missing_slots": ["target_area"], "clarification": "你想查询哪个纽约区域？例如 Astoria、LIC、Williamsburg。"}

    domain, result_type = infer_result_type(task_type)
    poi_limit = max(1, min(int(domain_context.get("point_limit") or 20), 20))
    queries: list[QuerySpec] = []

    if task_type == "neighborhood.crime_query":
        pattern = crime_pattern(query)
        queries.append(QuerySpec(
            purpose="analysis",
            execute_when="always",
            expected_result="safety_metrics_latest",
            domain="safety",
            sql=(
                "SELECT area_id, metric_date, crime_count_30d, crime_index_100, source_snapshot "
                "FROM v_area_metrics_latest WHERE area_id = :area_id LIMIT 1"
            ),
            params={"area_id": area_id},
        ))
        if pattern:
            queries.append(QuerySpec(
                purpose="detail",
                execute_when="always",
                expected_result="crime_count_by_requested_type",
                domain="safety",
                sql=(
                    "SELECT offense_category, COUNT(incident_id) AS crime_count "
                    "FROM app_crime_incident_snapshot "
                    "WHERE area_id = :area_id AND offense_category ILIKE :crime_pattern "
                    "GROUP BY offense_category ORDER BY crime_count DESC LIMIT 20"
                ),
                params={"area_id": area_id, "crime_pattern": pattern},
            ))
        else:
            queries.append(QuerySpec(
                purpose="detail",
                execute_when="always",
                expected_result="crime_count_by_category",
                domain="safety",
                sql=(
                    "SELECT offense_category, COUNT(incident_id) AS crime_count "
                    "FROM app_crime_incident_snapshot "
                    "WHERE area_id = :area_id "
                    "GROUP BY offense_category ORDER BY crime_count DESC LIMIT 20"
                ),
                params={"area_id": area_id},
            ))
    elif task_type == "neighborhood.convenience_query":
        queries.append(QuerySpec(
            purpose="analysis",
            execute_when="always",
            expected_result="convenience_count_by_category",
            domain="amenity",
            sql=(
                "SELECT category_code, category_name, SUM(facility_count) AS poi_count, MAX(metric_date) AS metric_date "
                "FROM app_area_convenience_category_daily "
                "WHERE area_id = :area_id GROUP BY category_code, category_name ORDER BY poi_count DESC LIMIT 20"
            ),
            params={"area_id": area_id},
        ))
        queries.append(QuerySpec(
            purpose="detail",
            execute_when="always",
            expected_result="sample_convenience_points",
            domain="amenity",
            sql=(
                "SELECT poi_id, category_code, category_name, name, latitude, longitude, source "
                "FROM app_map_poi_snapshot "
                "WHERE area_id = :area_id AND poi_type = :poi_type "
                f"ORDER BY category_code ASC, name ASC LIMIT {poi_limit}"
            ),
            params={"area_id": area_id, "poi_type": "convenience"},
        ))
    elif task_type == "neighborhood.entertainment_query":
        queries.append(QuerySpec(
            purpose="analysis",
            execute_when="always",
            expected_result="entertainment_count_by_category",
            domain="entertainment",
            sql=(
                "SELECT category_code, category_name, SUM(poi_count) AS poi_count, MAX(metric_date) AS metric_date "
                "FROM app_area_entertainment_category_daily "
                "WHERE area_id = :area_id GROUP BY category_code, category_name ORDER BY poi_count DESC LIMIT 20"
            ),
            params={"area_id": area_id},
        ))
        queries.append(QuerySpec(
            purpose="detail",
            execute_when="always",
            expected_result="sample_entertainment_points",
            domain="entertainment",
            sql=(
                "SELECT poi_id, category_code, category_name, name, latitude, longitude, source "
                "FROM app_map_poi_snapshot "
                "WHERE area_id = :area_id AND poi_type = :poi_type "
                f"ORDER BY category_code ASC, name ASC LIMIT {poi_limit}"
            ),
            params={"area_id": area_id, "poi_type": "entertainment"},
        ))
    else:
        queries.append(QuerySpec(
            purpose="analysis",
            execute_when="always",
            expected_result="area_metrics_latest",
            domain="safety",
            sql=(
                "SELECT area_id, metric_date, crime_count_30d, crime_index_100, entertainment_poi_count, "
                "convenience_facility_count, transit_station_count, complaint_noise_30d, source_snapshot "
                "FROM v_area_metrics_latest WHERE area_id = :area_id LIMIT 1"
            ),
            params={"area_id": area_id},
        ))

    return {
        "status": "sql_ready",
        "neighborhood_result_type": result_type,
        "area_id": area_id,
        "area_name": area_name,
        "queries": [q.__dict__ for q in queries],
        "default_applied": ["window_days_30"] if task_type == "neighborhood.crime_query" else [],
        "reason_summary": "基于 neighborhood schema 生成只读 SQL 查询计划。",
    }


def density_level(total: int) -> str:
    if total >= 50:
        return "high"
    if total >= 15:
        return "medium"
    if total >= 1:
        return "low"
    return "unknown"


def safety_level(crime_count: int | None, crime_index: float | None) -> str:
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


def summarize_results(task_type: str, plan: dict[str, Any], executions: list[dict[str, Any]]) -> dict[str, Any]:
    analysis = next((r for r in executions if r["purpose"] == "analysis"), None)
    detail = next((r for r in executions if r["purpose"] == "detail"), None)
    analysis_rows = (analysis or {}).get("data") or []
    detail_rows = (detail or {}).get("data") or []
    if not analysis_rows and not detail_rows:
        return {
            "status": "no_data",
            "domain": "neighborhood",
            "task_type": task_type,
            "neighborhood_result_type": plan.get("neighborhood_result_type"),
            "data_available": False,
            "missing_data_reason": "SQL 查询成功，但当前数据库中没有找到匹配区域画像数据。",
            "suggested_alternative": "可以扩大查询范围，或先运行对应的数据同步任务。",
            "source_tables": sorted({t for item in executions for t in item.get("source_tables", [])}),
        }

    metrics = analysis_rows[0] if analysis_rows else {}
    if task_type == "neighborhood.crime_query":
        total = metrics.get("crime_count_30d")
        index = metrics.get("crime_index_100")
        derived = {
            "area_id": plan.get("area_id"),
            "area_name": plan.get("area_name"),
            "total_crime_count_30d": total,
            "crime_index_100": index,
            "safety_level": safety_level(total, index),
            "crime_count_by_category": detail_rows,
        }
    elif task_type in {"neighborhood.convenience_query", "neighborhood.entertainment_query"}:
        total = int(sum(int(row.get("poi_count") or 0) for row in analysis_rows))
        derived = {
            "area_id": plan.get("area_id"),
            "area_name": plan.get("area_name"),
            "total_count": total,
            "count_by_category": analysis_rows,
            "top_categories": analysis_rows[:5],
            "poi_density_level": density_level(total),
            "sample_points": detail_rows[:20],
        }
    else:
        derived = {
            "area_id": plan.get("area_id"),
            "area_name": plan.get("area_name"),
            "metrics": metrics,
        }

    return {
        "status": "success",
        "domain": "neighborhood",
        "task_type": task_type,
        "neighborhood_result_type": plan.get("neighborhood_result_type"),
        "data_available": True,
        "sql_results": [{"purpose": r["purpose"], "status": r["status"], "row_count": len(r.get("data") or [])} for r in executions],
        "derived_metrics": derived,
        "data_context": {
            "metric_date": metrics.get("metric_date"),
            "data_quality": "reference",
            "source_snapshot": metrics.get("source_snapshot") or {},
            "fallback_used": False,
        },
        "display_refs": {"map_layer_ids": [], "display_result_ids": []},
        "source_tables": sorted({t for item in executions for t in item.get("source_tables", [])}),
        "default_applied": plan.get("default_applied", []),
    }
