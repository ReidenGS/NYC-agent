"""End-to-end coverage that POI / listing coordinates survive the full
plan -> execute -> normalize pipeline and end up in the final response payload.

Earlier tests only asserted that detail SQL strings contain `latitude` /
`longitude`, or fed lat/lng-less stub rows into the normalizer in isolation.
These tests close that gap by mocking only the planner and MCP boundary, then
asserting on the response payload produced by `handle_message`.
"""
from __future__ import annotations

import importlib
from types import MethodType

import pytest

from tests.conftest import add_service_to_path


@pytest.fixture
def nl_to_sql_mods():
    add_service_to_path("nl-to-sql-agent")
    main_mod = importlib.import_module("app.main")
    shared_mod = importlib.import_module("nyc_agent_shared.a2a_protocol")
    return main_mod, shared_mod


def _build_request(shared_mod, *, task_type: str, payload: dict):
    return shared_mod.build_request_message(
        task_type=task_type,
        payload=payload,
        trace_id="trace_test_coords",
        session_id="sess_test_coords",
        source_agent="orchestrator-agent",
        target_agent="nl-to-sql-agent",
    )


def _neighborhood_two_query_plan(task_type: str, *, domain: str, summary_table: str, poi_type: str) -> dict:
    return {
        "status": "sql_ready",
        "neighborhood_result_type": "entertainment_breakdown" if task_type == "neighborhood.entertainment_query" else "amenity_breakdown",
        "area_id": "QN0101",
        "area_name": "Astoria",
        "queries": [
            {
                "mcp_tool": f"mcp-{domain}.execute_readonly_sql",
                "target_table": summary_table,
                "domain": domain,
                "purpose": "analysis",
                "execute_when": "always",
                "expected_result": "count_by_category",
                "sql": f"SELECT category_code FROM {summary_table} WHERE area_id = :area_id LIMIT 1",
                "params": {"area_id": "QN0101"},
            },
            {
                "mcp_tool": f"mcp-{domain}.execute_readonly_sql",
                "target_table": "app_map_poi_snapshot",
                "domain": domain,
                "purpose": "detail",
                "execute_when": "always",
                "expected_result": "sample_points",
                "sql": "SELECT poi_id, name, latitude, longitude FROM app_map_poi_snapshot WHERE area_id = :area_id AND poi_type = :poi_type LIMIT 5",
                "params": {"area_id": "QN0101", "poi_type": poi_type},
            },
        ],
        "default_applied": [],
    }


@pytest.mark.parametrize(
    "task_type,domain,summary_table,poi_type,expected_layer",
    [
        (
            "neighborhood.entertainment_query",
            "entertainment",
            "app_area_entertainment_category_daily",
            "entertainment",
            "entertainment",
        ),
        (
            "neighborhood.convenience_query",
            "amenity",
            "app_area_convenience_category_daily",
            "convenience",
            "amenity",
        ),
    ],
)
def test_poi_coordinates_flow_into_display_refs_map_points(
    nl_to_sql_mods, monkeypatch, task_type, domain, summary_table, poi_type, expected_layer,
):
    main_mod, shared_mod = nl_to_sql_mods
    plan = _neighborhood_two_query_plan(task_type, domain=domain, summary_table=summary_table, poi_type=poi_type)

    def fake_generate_sql_plan(self, *, task_type, query, slots, domain_context):
        return plan

    poi_rows = [
        {"poi_id": "P1", "name": "Spot 1", "latitude": 40.7611, "longitude": -73.9920, "category_code": "bar"},
        {"poi_id": "P2", "name": "Spot 2", "latitude": 40.7600, "longitude": -73.9800, "category_code": "park"},
    ]

    def fake_execute_query(_session_id, _task_type, query):
        if query["purpose"] == "analysis":
            return {
                "status": "success",
                "data": [{"category_code": "bar", "category_name": "酒吧", "poi_count": 7}],
                "source_tables": [summary_table],
                "purpose": "analysis",
                "error": None,
            }
        return {
            "status": "success",
            "data": poi_rows,
            "source_tables": ["app_map_poi_snapshot"],
            "purpose": "detail",
            "error": None,
        }

    monkeypatch.setattr(
        main_mod.server.planner,
        "generate_sql_plan",
        MethodType(fake_generate_sql_plan, main_mod.server.planner),
    )
    monkeypatch.setattr(main_mod, "execute_query", fake_execute_query)

    request = _build_request(
        shared_mod,
        task_type=task_type,
        payload={"domain_user_query": "Astoria 周边？", "slots": {"area_id": {"value": "QN0101"}}, "domain_context": {}},
    )
    response = main_mod.server.handle_message(request)
    content = shared_mod.extract_response_content(response)

    assert content["status"] == "success"
    result = (content.get("payload") or {}).get("neighborhood_result") or {}
    assert result.get("status") == "success"
    display_refs = result.get("display_refs") or {}
    assert display_refs.get("map_layer_ids") == [expected_layer]
    map_points = display_refs.get("map_points") or []
    assert len(map_points) == len(poi_rows)
    for point in map_points:
        assert "latitude" in point and "longitude" in point
        assert isinstance(point["latitude"], float)
        assert isinstance(point["longitude"], float)
    assert {p["poi_id"] for p in map_points} == {"P1", "P2"}


def _housing_listing_plan(*, with_budget: bool) -> dict:
    detail = {
        "mcp_tool": "mcp-housing.execute_readonly_sql",
        "target_table": "app_area_rental_listing_snapshot",
        "domain": "housing",
        "purpose": "detail",
        "execute_when": "always",
        "expected_result": "listing_candidates",
        "sql": (
            "SELECT listing_id, formatted_address, bedroom_type, monthly_rent, "
            "latitude, longitude, listing_status, last_seen_date "
            "FROM app_area_rental_listing_snapshot "
            "WHERE area_id = :area_id AND bedroom_type = :bedroom_type AND listing_status = :active_status "
            "ORDER BY monthly_rent ASC LIMIT 5"
        ),
        "params": {"area_id": "QN0101", "bedroom_type": "1br", "active_status": "active"},
    }
    fallback = {
        "mcp_tool": "mcp-housing.execute_readonly_sql",
        "target_table": "app_area_rental_listing_snapshot",
        "domain": "housing",
        "purpose": "fallback",
        "execute_when": "detail_no_data",
        "expected_result": "recent_seen_listings",
        "sql": (
            "SELECT listing_id, formatted_address, bedroom_type, monthly_rent, "
            "latitude, longitude, listing_status, last_seen_date "
            "FROM app_area_rental_listing_snapshot "
            "WHERE area_id = :area_id AND bedroom_type = :bedroom_type "
            "ORDER BY last_seen_date DESC, monthly_rent ASC NULLS LAST LIMIT 5"
        ),
        "params": {"area_id": "QN0101", "bedroom_type": "1br"},
    }
    return {
        "status": "sql_ready",
        "housing_result_type": "listing_candidates",
        "area_id": "QN0101",
        "area_name": "Astoria",
        "bedroom_type": "1br",
        "budget_monthly": 3000.0 if with_budget else None,
        "queries": [detail, fallback],
        "default_applied": [],
    }


def test_housing_listing_search_active_listing_coordinates_flow_through(nl_to_sql_mods, monkeypatch):
    main_mod, shared_mod = nl_to_sql_mods
    plan = _housing_listing_plan(with_budget=False)

    listing_rows = [
        {
            "listing_id": "L1",
            "formatted_address": "1 Test Ave",
            "bedroom_type": "1br",
            "monthly_rent": 2800,
            "latitude": 40.7530,
            "longitude": -73.9210,
            "listing_status": "active",
            "last_seen_date": "2025-05-10",
        },
        {
            "listing_id": "L2",
            "formatted_address": "2 Test Ave",
            "bedroom_type": "1br",
            "monthly_rent": 2900,
            "latitude": 40.7540,
            "longitude": -73.9220,
            "listing_status": "active",
            "last_seen_date": "2025-05-12",
        },
    ]

    def fake_generate_sql_plan(self, *, task_type, query, slots, domain_context):
        return plan

    def fake_execute_query(_session_id, _task_type, query):
        if query["purpose"] == "detail":
            return {
                "status": "success",
                "data": listing_rows,
                "source_tables": ["app_area_rental_listing_snapshot"],
                "purpose": "detail",
                "error": None,
            }
        raise AssertionError("fallback should be skipped when detail has data")

    monkeypatch.setattr(
        main_mod.server.planner,
        "generate_sql_plan",
        MethodType(fake_generate_sql_plan, main_mod.server.planner),
    )
    monkeypatch.setattr(main_mod, "execute_query", fake_execute_query)

    request = _build_request(
        shared_mod,
        task_type="housing.listing_search",
        payload={
            "domain_user_query": "Astoria 1b 房源？",
            "slots": {"area_id": {"value": "QN0101"}, "bedroom_type": {"value": "1br"}},
            "domain_context": {},
        },
    )
    response = main_mod.server.handle_message(request)
    content = shared_mod.extract_response_content(response)

    assert content["status"] == "success"
    housing_result = (content.get("payload") or {}).get("housing_result") or {}
    assert housing_result.get("status") == "success"
    assert housing_result["data_context"]["fallback_used"] is False
    candidates = housing_result.get("listing_candidates") or []
    assert len(candidates) == len(listing_rows)
    for row in candidates:
        assert "latitude" in row and "longitude" in row
        assert isinstance(row["latitude"], float)
        assert isinstance(row["longitude"], float)
    assert {row["listing_id"] for row in candidates} == {"L1", "L2"}


def test_housing_listing_search_fallback_coordinates_flow_through(nl_to_sql_mods, monkeypatch):
    main_mod, shared_mod = nl_to_sql_mods
    plan = _housing_listing_plan(with_budget=False)

    fallback_rows = [
        {
            "listing_id": "L9",
            "formatted_address": "9 Test Ave",
            "bedroom_type": "1br",
            "monthly_rent": 3050,
            "latitude": 40.7600,
            "longitude": -73.9100,
            "listing_status": "expired",
            "last_seen_date": "2025-04-20",
        }
    ]

    def fake_generate_sql_plan(self, *, task_type, query, slots, domain_context):
        return plan

    def fake_execute_query(_session_id, _task_type, query):
        if query["purpose"] == "detail":
            return {
                "status": "success",
                "data": [],
                "source_tables": ["app_area_rental_listing_snapshot"],
                "purpose": "detail",
                "error": None,
            }
        return {
            "status": "success",
            "data": fallback_rows,
            "source_tables": ["app_area_rental_listing_snapshot"],
            "purpose": "fallback",
            "error": None,
        }

    monkeypatch.setattr(
        main_mod.server.planner,
        "generate_sql_plan",
        MethodType(fake_generate_sql_plan, main_mod.server.planner),
    )
    monkeypatch.setattr(main_mod, "execute_query", fake_execute_query)

    request = _build_request(
        shared_mod,
        task_type="housing.listing_search",
        payload={
            "domain_user_query": "Astoria 1b 房源？",
            "slots": {"area_id": {"value": "QN0101"}, "bedroom_type": {"value": "1br"}},
            "domain_context": {},
        },
    )
    response = main_mod.server.handle_message(request)
    content = shared_mod.extract_response_content(response)

    assert content["status"] == "success"
    housing_result = (content.get("payload") or {}).get("housing_result") or {}
    assert housing_result["data_context"]["fallback_used"] is True
    assert housing_result["data_context"]["not_realtime_inventory"] is True
    candidates = housing_result.get("listing_candidates") or []
    assert len(candidates) == 1
    row = candidates[0]
    assert "latitude" in row and "longitude" in row
    assert row["latitude"] == pytest.approx(40.7600)
    assert row["longitude"] == pytest.approx(-73.9100)
    assert row["fallback_used"] is True
    assert row["availability"] == "stale_or_unknown"
