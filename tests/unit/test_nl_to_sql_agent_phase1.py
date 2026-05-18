from __future__ import annotations

import pytest

from tests.conftest import add_service_to_path


@pytest.fixture(autouse=True)
def _nl_to_sql_path():
    add_service_to_path("nl-to-sql-agent")


def test_phase1_skill_loader_loads_neighborhood_prompt():
    from app.skill_loader import load_skill_prompt

    prompt = load_skill_prompt("neighborhood.entertainment_query")

    assert "Common SQL Rules" in prompt
    assert "neighborhood.entertainment_query" in prompt
    assert "app_map_poi_snapshot" in prompt
    assert "app_area_entertainment_category_daily" in prompt
    assert "app_area_convenience_category_daily" not in prompt


def test_phase1_skill_loader_injects_only_convenience_tables_for_convenience():
    from app.skill_loader import load_skill_prompt

    prompt = load_skill_prompt("neighborhood.convenience_query")

    assert "Common SQL Rules" in prompt
    assert "neighborhood.convenience_query" in prompt
    assert "app_map_poi_snapshot" in prompt
    assert "app_area_convenience_category_daily" in prompt
    assert "app_area_entertainment_category_daily" not in prompt


def test_planner_prompt_no_longer_has_global_database_schema_slot():
    from app.llm_planner import PLAN_PROMPT

    assert "database_schema" not in PLAN_PROMPT.input_variables


def test_deterministic_phase1_plan_includes_poi_coordinates():
    from app.llm_planner import deterministic_plan, validate_plan

    plan = deterministic_plan(
        "neighborhood.convenience_query",
        "Astoria 有哪些便利设施？",
        {
            "area_id": {"value": "QN0101", "source": "area_rag", "confidence": 0.95},
            "area_name": {"value": "Astoria", "source": "area_rag", "confidence": 0.95},
        },
        {"point_limit": 20},
    )

    validate_plan(plan, "neighborhood.convenience_query")
    detail_sql = next(q["sql"] for q in plan["queries"] if q["purpose"] == "detail")
    assert "app_map_poi_snapshot" in detail_sql
    assert "latitude" in detail_sql
    assert "longitude" in detail_sql


def test_tool_catalog_includes_sql_tools():
    from app.tool_registry import render_mcp_tool_catalog

    catalog = render_mcp_tool_catalog()

    assert "mcp-entertainment.execute_readonly_sql" in catalog
    assert "mcp-amenity.execute_readonly_sql" in catalog
    assert "mcp-housing.execute_readonly_sql" in catalog


def test_planner_validation_requires_mcp_tool():
    from app.llm_planner import deterministic_plan, validate_plan
    from nyc_agent_shared.llm_client import LlmClientError

    plan = deterministic_plan(
        "neighborhood.convenience_query",
        "Astoria 有哪些便利设施？",
        {"area_id": {"value": "QN0101"}},
        {},
    )
    del plan["queries"][0]["mcp_tool"]

    with pytest.raises(LlmClientError, match="mcp_tool"):
        validate_plan(plan, "neighborhood.convenience_query")


def test_mcp_router_rejects_unknown_tool():
    from app.mcp_router import execute_query

    with pytest.raises(ValueError, match="unsupported MCP SQL tool"):
        execute_query(
            None,
            "neighborhood.entertainment_query",
            {
                "mcp_tool": "mcp-unknown.execute_readonly_sql",
                "target_table": "app_map_poi_snapshot",
                "domain": "entertainment",
                "purpose": "detail",
                "sql": "SELECT poi_id, latitude, longitude FROM app_map_poi_snapshot WHERE area_id = :area_id LIMIT 20",
                "params": {"area_id": "MN0402"},
            },
        )


def test_mcp_router_rejects_tool_domain_mismatch():
    from app.mcp_router import execute_query

    with pytest.raises(ValueError, match="not allowed"):
        execute_query(
            None,
            "neighborhood.entertainment_query",
            {
                "mcp_tool": "mcp-entertainment.execute_readonly_sql",
                "target_table": "app_map_poi_snapshot",
                "domain": "amenity",
                "purpose": "detail",
                "sql": "SELECT poi_id, latitude, longitude FROM app_map_poi_snapshot WHERE area_id = :area_id LIMIT 20",
                "params": {"area_id": "MN0402"},
            },
        )


def test_mcp_router_uses_query_mcp_tool(monkeypatch):
    from app import mcp_router

    calls = []

    def fake_call(tool_id, arguments):
        calls.append((tool_id, arguments))
        return {"status": "success", "data": [{"ok": True}], "source_tables": ["app_area_rental_market_daily"], "error": None}

    monkeypatch.setattr(mcp_router, "call_mcp_tool", fake_call)

    result = mcp_router.execute_query(
        "sess_test",
        "housing.rent_query",
        {
            "mcp_tool": "mcp-housing.execute_readonly_sql",
            "target_table": "app_area_rental_market_daily",
            "domain": "housing",
            "purpose": "analysis",
            "expected_result": "rent_range_by_bedroom",
            "sql": "SELECT area_id, bedroom_type, rent_median FROM app_area_rental_market_daily WHERE area_id = :area_id LIMIT 1",
            "params": {"area_id": "QN0101"},
        },
    )

    assert calls[0][0] == "mcp-housing.execute_readonly_sql"
    assert calls[0][1]["session_id"] == "sess_test"
    assert result["data"] == [{"ok": True}]


def test_deterministic_housing_rent_plan_includes_mcp_tool():
    from app.llm_planner import deterministic_plan, validate_plan

    plan = deterministic_plan(
        "housing.rent_query",
        "Astoria 3000 美元能租到 1b 吗？",
        {
            "area_id": {"value": "QN0101"},
            "area_name": {"value": "Astoria"},
            "bedroom_type": {"value": "1br"},
            "budget_monthly": {"value": 3000},
        },
        {"listing_limit": 5},
    )

    validate_plan(plan, "housing.rent_query")
    assert plan["housing_result_type"] == "budget_fit"
    assert all(q["mcp_tool"] == "mcp-housing.execute_readonly_sql" for q in plan["queries"])


def test_deterministic_housing_listing_requires_bedroom_type():
    from app.llm_planner import deterministic_plan

    plan = deterministic_plan(
        "housing.listing_search",
        "Astoria 有哪些房源？",
        {"area_id": {"value": "QN0101"}, "area_name": {"value": "Astoria"}},
        {},
    )

    assert plan["status"] == "clarification_required"
    assert "bedroom_type" in plan["missing_slots"]


def test_orchestrator_routes_phase1_intents_to_nl_to_sql(monkeypatch):
    add_service_to_path("orchestrator-agent")
    from app.nodes import plan_execute as plan_execute_mod
    from app.nodes.plan_execute import plan_execute
    from app.state import OrchestratorState

    calls = []

    def fake_call_agent(target, **kwargs):
        calls.append((target, kwargs))
        return {"status": "success", "payload": {"ok": True}, "error": None}

    monkeypatch.setattr(plan_execute_mod, "call_agent", fake_call_agent)

    result = plan_execute(
        OrchestratorState(
            session_id="sess_test",
            trace_id="trace_test",
            current_user_message="Astoria 有哪些娱乐设施？",
            intent="neighborhood.entertainment_query",
            target_area_id="QN0101",
            target_area_name="Astoria",
        )
    )

    assert calls
    assert calls[0][0] == "nl-to-sql"
    assert calls[0][1]["task_type"] == "neighborhood.entertainment_query"
    assert result["agent_results"][0].agent == "nl-to-sql-agent"


def test_deterministic_listing_search_plan_has_active_and_fallback_queries():
    from app.llm_planner import deterministic_plan, validate_plan

    plan = deterministic_plan(
        "housing.listing_search",
        "Astoria 有哪些 1b 房源？",
        {
            "area_id": {"value": "QN0101"},
            "area_name": {"value": "Astoria"},
            "bedroom_type": {"value": "1br"},
        },
        {},
    )

    validate_plan(plan, "housing.listing_search")
    purposes = [q["purpose"] for q in plan["queries"]]
    assert purposes == ["detail", "fallback"]

    detail = plan["queries"][0]
    fallback = plan["queries"][1]
    assert detail["execute_when"] == "always"
    assert detail["target_table"] == "app_area_rental_listing_snapshot"
    assert "listing_status = :active_status" in detail["sql"]
    assert detail["params"]["active_status"] == "active"
    assert "latitude" in detail["sql"] and "longitude" in detail["sql"]

    assert fallback["execute_when"] == "detail_no_data"
    assert fallback["expected_result"] == "recent_seen_listings"
    assert "listing_status = :active_status" not in fallback["sql"]
    assert "active_status" not in fallback["params"]
    assert "ORDER BY last_seen_date DESC, monthly_rent ASC NULLS LAST" in fallback["sql"]
    for forbidden in ("listing_agent_name", "listing_agent_phone", "raw_source", "geom"):
        assert forbidden not in detail["sql"]
        assert forbidden not in fallback["sql"]


def test_deterministic_listing_search_budget_propagates_to_both_queries():
    from app.llm_planner import deterministic_plan, validate_plan

    plan = deterministic_plan(
        "housing.listing_search",
        "Astoria 3000 美元能租到 1b 吗？",
        {
            "area_id": {"value": "QN0101"},
            "area_name": {"value": "Astoria"},
            "bedroom_type": {"value": "1br"},
            "budget_monthly": {"value": 3000},
        },
        {},
    )

    validate_plan(plan, "housing.listing_search")
    for query in plan["queries"]:
        assert "monthly_rent <= :budget_monthly" in query["sql"]
        assert query["params"]["budget_monthly"] == 3000.0


def test_deterministic_listing_search_listing_limit_caps_at_10():
    from app.llm_planner import deterministic_plan

    plan = deterministic_plan(
        "housing.listing_search",
        "Astoria 有哪些 1b 房源？",
        {
            "area_id": {"value": "QN0101"},
            "bedroom_type": {"value": "1br"},
        },
        {"listing_limit": 20},
    )

    assert all("LIMIT 10" in q["sql"] for q in plan["queries"])


def test_validate_plan_rejects_listing_detail_without_coordinates():
    from app.llm_planner import deterministic_plan, validate_plan
    from nyc_agent_shared.llm_client import LlmClientError

    plan = deterministic_plan(
        "housing.listing_search",
        "Astoria 有哪些 1b 房源？",
        {
            "area_id": {"value": "QN0101"},
            "bedroom_type": {"value": "1br"},
        },
        {},
    )
    detail = plan["queries"][0]
    detail["sql"] = detail["sql"].replace("latitude, longitude, ", "")

    with pytest.raises(LlmClientError, match="latitude and longitude"):
        validate_plan(plan, "housing.listing_search")


def test_validate_plan_rejects_listing_with_forbidden_columns():
    from app.llm_planner import deterministic_plan, validate_plan
    from nyc_agent_shared.llm_client import LlmClientError

    plan = deterministic_plan(
        "housing.listing_search",
        "Astoria 有哪些 1b 房源？",
        {
            "area_id": {"value": "QN0101"},
            "bedroom_type": {"value": "1br"},
        },
        {},
    )
    detail = plan["queries"][0]
    detail["sql"] = detail["sql"].replace("source", "source, listing_agent_phone")

    with pytest.raises(LlmClientError, match="listing_agent_phone"):
        validate_plan(plan, "housing.listing_search")


def test_summarize_housing_listing_search_prefers_active_listings():
    from app.result_normalizer import summarize_housing_results

    plan = {
        "housing_result_type": "listing_candidates",
        "area_id": "QN0101",
        "area_name": "Astoria",
        "bedroom_type": "1br",
        "budget_monthly": 3000.0,
    }
    executions = [
        {
            "purpose": "detail",
            "status": "success",
            "data": [{"listing_id": "L1", "monthly_rent": 2800, "listing_status": "active"}],
            "source_tables": ["app_area_rental_listing_snapshot"],
        },
        {
            "purpose": "fallback",
            "status": "success",
            "data": [],
            "source_tables": ["app_area_rental_listing_snapshot"],
        },
    ]

    result = summarize_housing_results("housing.listing_search", plan, executions)

    assert result["status"] == "success"
    assert result["data_context"]["fallback_used"] is False
    assert result["data_context"]["not_realtime_inventory"] is False
    assert [c["listing_id"] for c in result["listing_candidates"]] == ["L1"]
    assert result["derived_metrics"]["matching_listing_count"] == 1


def test_summarize_housing_listing_search_uses_fallback_when_active_empty():
    from app.result_normalizer import summarize_housing_results

    plan = {
        "housing_result_type": "listing_candidates",
        "area_id": "QN0101",
        "area_name": "Astoria",
        "bedroom_type": "1br",
        "budget_monthly": None,
    }
    executions = [
        {
            "purpose": "detail",
            "status": "success",
            "data": [],
            "source_tables": ["app_area_rental_listing_snapshot"],
        },
        {
            "purpose": "fallback",
            "status": "success",
            "data": [{"listing_id": "L9", "monthly_rent": 3100, "listing_status": "expired"}],
            "source_tables": ["app_area_rental_listing_snapshot"],
        },
    ]

    result = summarize_housing_results("housing.listing_search", plan, executions)

    assert result["status"] == "success"
    assert result["data_context"]["fallback_used"] is True
    assert result["data_context"]["not_realtime_inventory"] is True
    candidates = result["listing_candidates"]
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["fallback_used"] is True
    assert candidate["not_realtime_inventory"] is True
    assert candidate["availability"] == "stale_or_unknown"
    assert candidate["data_quality"] == "reference"


def test_summarize_housing_listing_search_no_data_when_both_empty():
    from app.result_normalizer import summarize_housing_results

    plan = {
        "housing_result_type": "listing_candidates",
        "area_id": "QN0101",
        "area_name": "Astoria",
        "bedroom_type": "1br",
        "budget_monthly": None,
    }
    executions = [
        {"purpose": "detail", "status": "success", "data": [], "source_tables": ["app_area_rental_listing_snapshot"]},
        {"purpose": "fallback", "status": "success", "data": [], "source_tables": ["app_area_rental_listing_snapshot"]},
    ]

    result = summarize_housing_results("housing.listing_search", plan, executions)

    assert result["status"] == "no_data"
    assert result["data_available"] is False
    assert result["listing_candidates"] == []


def test_orchestrator_routes_housing_intents_to_nl_to_sql(monkeypatch):
    add_service_to_path("orchestrator-agent")
    from app.nodes import plan_execute as plan_execute_mod
    from app.nodes.plan_execute import plan_execute
    from app.state import OrchestratorState

    calls = []

    def fake_call_agent(target, **kwargs):
        calls.append((target, kwargs))
        return {"status": "success", "payload": {"ok": True}, "error": None}

    monkeypatch.setattr(plan_execute_mod, "call_agent", fake_call_agent)

    result = plan_execute(
        OrchestratorState(
            session_id="sess_test",
            trace_id="trace_test",
            current_user_message="Astoria 3000 美元能租到 1b 吗？",
            intent="housing.rent_query",
            target_area_id="QN0101",
            target_area_name="Astoria",
            constraints={"budget_monthly": 3000, "bedroom_type": "1br"},
        )
    )

    assert calls
    assert calls[0][0] == "nl-to-sql"
    assert calls[0][1]["task_type"] == "housing.rent_query"
    assert result["agent_results"][0].agent == "nl-to-sql-agent"
