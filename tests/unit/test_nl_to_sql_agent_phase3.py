from __future__ import annotations

import pytest

from tests.conftest import add_service_to_path


@pytest.fixture(autouse=True)
def _nl_to_sql_path():
    add_service_to_path("nl-to-sql-agent")


def test_phase3_skill_loader_loads_crime_references():
    from app.skill_loader import load_skill_prompt

    prompt = load_skill_prompt("neighborhood.crime_query")

    assert "neighborhood.crime_query" in prompt
    assert "v_area_metrics_latest" in prompt
    assert "app_crime_incident_snapshot" in prompt
    assert "app_area_entertainment_category_daily" not in prompt
    assert "app_area_convenience_category_daily" not in prompt
    assert "app_area_rental_market_daily" not in prompt


def test_phase3_skill_loader_loads_area_metrics_references():
    from app.skill_loader import load_skill_prompt

    prompt = load_skill_prompt("area.metrics_query")

    assert "area.metrics_query" in prompt
    assert "v_area_metrics_latest" in prompt
    assert "app_crime_incident_snapshot" not in prompt
    assert "app_map_poi_snapshot" not in prompt


def test_tool_catalog_includes_safety_tool():
    from app.tool_registry import render_mcp_tool_catalog

    catalog = render_mcp_tool_catalog()

    assert "mcp-safety.execute_readonly_sql" in catalog
    assert "v_area_metrics_latest" in catalog
    assert "app_crime_incident_snapshot" in catalog


def test_deterministic_crime_plan_general_breakdown():
    from app.llm_planner import deterministic_plan, validate_plan

    plan = deterministic_plan(
        "neighborhood.crime_query",
        "Astoria 安不安全？",
        {"area_id": {"value": "QN0101"}, "area_name": {"value": "Astoria"}},
        {},
    )

    validate_plan(plan, "neighborhood.crime_query")
    assert plan["neighborhood_result_type"] == "crime_breakdown"
    assert [q["purpose"] for q in plan["queries"]] == ["analysis", "detail"]
    analysis, detail = plan["queries"]
    assert analysis["target_table"] == "v_area_metrics_latest"
    assert "crime_count_30d" in analysis["sql"]
    assert "crime_index_100" in analysis["sql"]
    assert detail["target_table"] == "app_crime_incident_snapshot"
    assert detail["expected_result"] == "crime_count_by_category"
    assert "offense_category ILIKE" not in detail["sql"]
    assert "crime_pattern" not in detail["params"]
    for q in plan["queries"]:
        assert q["mcp_tool"] == "mcp-safety.execute_readonly_sql"
        assert q["domain"] == "safety"
        assert "latitude" not in q["sql"].lower()


def test_deterministic_crime_plan_pattern_match():
    from app.llm_planner import deterministic_plan, validate_plan

    plan = deterministic_plan(
        "neighborhood.crime_query",
        "Astoria burglary 多吗？",
        {"area_id": {"value": "QN0101"}},
        {},
    )

    validate_plan(plan, "neighborhood.crime_query")
    detail = next(q for q in plan["queries"] if q["purpose"] == "detail")
    assert detail["expected_result"] == "crime_count_by_requested_type"
    assert "offense_category ILIKE :crime_pattern" in detail["sql"]
    assert detail["params"]["crime_pattern"] == "%BURGLARY%"


def test_deterministic_crime_plan_unsupported_keyword():
    from app.llm_planner import deterministic_plan

    plan = deterministic_plan(
        "neighborhood.crime_query",
        "Astoria 街灯亮吗？",
        {"area_id": {"value": "QN0101"}},
        {},
    )

    assert plan["status"] == "unsupported_data_request"
    assert plan["queries"] == []
    assert "街道照明" in plan["unsupported_reason"]


def test_deterministic_crime_plan_requires_area():
    from app.llm_planner import deterministic_plan

    plan = deterministic_plan(
        "neighborhood.crime_query",
        "这里安不安全？",
        {},
        {},
    )

    assert plan["status"] == "clarification_required"
    assert plan["missing_slots"] == ["target_area"]


def test_deterministic_area_metrics_plan():
    from app.llm_planner import deterministic_plan, validate_plan

    plan = deterministic_plan(
        "area.metrics_query",
        "Astoria 整体怎么样？",
        {"area_id": {"value": "QN0101"}, "area_name": {"value": "Astoria"}},
        {},
    )

    validate_plan(plan, "area.metrics_query")
    assert plan["neighborhood_result_type"] == "area_overview"
    assert len(plan["queries"]) == 1
    only = plan["queries"][0]
    assert only["purpose"] == "analysis"
    assert only["target_table"] == "v_area_metrics_latest"
    assert only["mcp_tool"] == "mcp-safety.execute_readonly_sql"
    for column in (
        "crime_count_30d",
        "crime_index_100",
        "entertainment_poi_count",
        "convenience_facility_count",
        "transit_station_count",
        "complaint_noise_30d",
    ):
        assert column in only["sql"]


def test_validate_plan_rejects_safety_domain_for_amenity_task():
    from app.llm_planner import deterministic_plan, validate_plan
    from nyc_agent_shared.llm_client import LlmClientError

    plan = deterministic_plan(
        "neighborhood.crime_query",
        "Astoria 安不安全？",
        {"area_id": {"value": "QN0101"}},
        {},
    )
    plan["queries"][0]["mcp_tool"] = "mcp-amenity.execute_readonly_sql"

    with pytest.raises(LlmClientError):
        validate_plan(plan, "neighborhood.crime_query")


def test_validate_plan_accepts_crime_without_poi_coordinates():
    from app.llm_planner import deterministic_plan, validate_plan

    plan = deterministic_plan(
        "neighborhood.crime_query",
        "Astoria 安全吗？",
        {"area_id": {"value": "QN0101"}},
        {},
    )

    validate_plan(plan, "neighborhood.crime_query")


def test_mcp_router_rejects_safety_tool_for_amenity_target_table():
    from app.mcp_router import execute_query

    with pytest.raises(ValueError, match="not allowed"):
        execute_query(
            None,
            "neighborhood.crime_query",
            {
                "mcp_tool": "mcp-safety.execute_readonly_sql",
                "target_table": "app_map_poi_snapshot",
                "domain": "safety",
                "purpose": "detail",
                "sql": "SELECT poi_id FROM app_map_poi_snapshot WHERE area_id = :area_id LIMIT 1",
                "params": {"area_id": "QN0101"},
            },
        )


def test_summarize_crime_results_uses_metrics_and_categories():
    from app.result_normalizer import summarize_neighborhood_results

    plan = {
        "neighborhood_result_type": "crime_breakdown",
        "area_id": "QN0101",
        "area_name": "Astoria",
    }
    executions = [
        {
            "purpose": "analysis",
            "status": "success",
            "data": [{
                "area_id": "QN0101",
                "metric_date": "2025-05-01",
                "crime_count_30d": 120,
                "crime_index_100": 55,
                "source_snapshot": {"crime": "nypd_complaint"},
            }],
            "source_tables": ["v_area_metrics_latest"],
        },
        {
            "purpose": "detail",
            "status": "success",
            "data": [
                {"offense_category": "LARCENY", "crime_count": 40},
                {"offense_category": "ASSAULT", "crime_count": 30},
            ],
            "source_tables": ["app_crime_incident_snapshot"],
        },
    ]

    result = summarize_neighborhood_results("neighborhood.crime_query", plan, executions)

    assert result["status"] == "success"
    assert result["derived_metrics"]["total_crime_count_30d"] == 120
    assert result["derived_metrics"]["crime_index_100"] == 55
    assert result["derived_metrics"]["safety_level"] == "medium_risk"
    assert [c["offense_category"] for c in result["derived_metrics"]["crime_count_by_category"]] == ["LARCENY", "ASSAULT"]
    assert result["data_context"]["source_snapshot"] == {"crime": "nypd_complaint"}
    assert result["display_refs"]["map_layer_ids"] == []
    assert result["display_refs"]["map_points"] == []


def test_summarize_area_metrics_flattens_single_row():
    from app.result_normalizer import summarize_neighborhood_results

    plan = {
        "neighborhood_result_type": "area_overview",
        "area_id": "QN0101",
        "area_name": "Astoria",
    }
    executions = [
        {
            "purpose": "analysis",
            "status": "success",
            "data": [{
                "area_id": "QN0101",
                "metric_date": "2025-05-01",
                "crime_count_30d": 80,
                "crime_index_100": 32,
                "entertainment_poi_count": 12,
                "convenience_facility_count": 22,
                "transit_station_count": 4,
                "complaint_noise_30d": 7,
                "source_snapshot": {"safety": "snapshot"},
            }],
            "source_tables": ["v_area_metrics_latest"],
        },
    ]

    result = summarize_neighborhood_results("area.metrics_query", plan, executions)

    assert result["status"] == "success"
    metrics = result["derived_metrics"]["metrics"]
    assert metrics["entertainment_poi_count"] == 12
    assert metrics["transit_station_count"] == 4
    assert result["data_context"]["metric_date"] == "2025-05-01"
    assert result["display_refs"]["map_layer_ids"] == []


def test_summarize_safety_no_data_when_executions_empty():
    from app.result_normalizer import summarize_neighborhood_results

    plan = {
        "neighborhood_result_type": "crime_breakdown",
        "area_id": "QN0101",
        "area_name": "Astoria",
    }
    executions = [
        {"purpose": "analysis", "status": "success", "data": [], "source_tables": ["v_area_metrics_latest"]},
        {"purpose": "detail", "status": "success", "data": [], "source_tables": ["app_crime_incident_snapshot"]},
    ]

    result = summarize_neighborhood_results("neighborhood.crime_query", plan, executions)

    assert result["status"] == "no_data"
    assert result["data_available"] is False


def test_orchestrator_routes_phase3_intents_to_nl_to_sql(monkeypatch):
    add_service_to_path("orchestrator-agent")
    from app.nodes import plan_execute as plan_execute_mod
    from app.nodes.plan_execute import plan_execute
    from app.state import OrchestratorState

    calls = []

    def fake_call_agent(target, **kwargs):
        calls.append((target, kwargs))
        return {"status": "success", "payload": {"ok": True}, "error": None}

    monkeypatch.setattr(plan_execute_mod, "call_agent", fake_call_agent)

    for intent in ("neighborhood.crime_query", "area.metrics_query"):
        calls.clear()
        result = plan_execute(
            OrchestratorState(
                session_id="sess_test",
                trace_id="trace_test",
                current_user_message="Astoria 安不安全？",
                intent=intent,
                target_area_id="QN0101",
                target_area_name="Astoria",
            )
        )
        assert calls and calls[0][0] == "nl-to-sql", intent
        assert calls[0][1]["task_type"] == intent
        assert result["agent_results"][0].agent == "nl-to-sql-agent"
