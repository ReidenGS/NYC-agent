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


def _build_request_message(shared_mod, *, task_type: str, payload: dict):
    return shared_mod.build_request_message(
        task_type=task_type,
        payload=payload,
        trace_id="trace_test_nl_to_sql_retry",
        session_id="sess_test_nl_to_sql_retry",
        source_agent="orchestrator-agent",
        target_agent="nl-to-sql-agent",
    )


def _stub_plan(task_type: str) -> dict:
    return {
        "status": "sql_ready",
        "neighborhood_result_type": "amenity_breakdown",
        "area_id": "QN0101",
        "area_name": "Astoria",
        "queries": [
            {
                "mcp_tool": "mcp-amenity.execute_readonly_sql",
                "target_table": "app_area_convenience_category_daily",
                "domain": "amenity",
                "purpose": "analysis",
                "execute_when": "always",
                "expected_result": "convenience_count_by_category",
                "sql": "SELECT category_code FROM app_area_convenience_category_daily WHERE area_id = :area_id LIMIT 1",
                "params": {"area_id": "QN0101"},
            }
        ],
        "default_applied": [],
    }


def test_mcp_validation_error_retries_three_times_then_no_data(nl_to_sql_mods, monkeypatch):
    main_mod, shared_mod = nl_to_sql_mods
    observed_queries: list[str] = []

    def fake_generate_sql_plan(self, *, task_type, query, slots, domain_context):
        observed_queries.append(query)
        return _stub_plan(task_type)

    def fake_execute_query(_session_id, _task_type, _query):
        return {
            "status": "validation_error",
            "error": {"message": "forbidden table"},
            "data": [],
            "source_tables": [],
            "purpose": "analysis",
        }

    monkeypatch.setattr(
        main_mod.server.planner,
        "generate_sql_plan",
        MethodType(fake_generate_sql_plan, main_mod.server.planner),
    )
    monkeypatch.setattr(main_mod, "execute_query", fake_execute_query)

    request = _build_request_message(
        shared_mod,
        task_type="neighborhood.convenience_query",
        payload={"domain_user_query": "Astoria 便利设施？", "slots": {"area_id": {"value": "QN0101"}}, "domain_context": {}},
    )
    response = main_mod.server.handle_message(request)
    content = shared_mod.extract_response_content(response)

    assert content["status"] == "no_data"
    payload = content.get("payload") or {}
    assert payload.get("reason") == "mcp_sql_validation_retry_exhausted"
    assert payload.get("mcp_retry_attempts") == 3
    assert payload.get("planner_error") == "forbidden table"
    assert payload.get("sql_plan")
    assert len(observed_queries) == 3
    assert "[MCP SQL 校验器返回的错误]" in observed_queries[1]
    assert "forbidden table" in observed_queries[1]
    assert "[MCP SQL 校验器返回的错误]" in observed_queries[2]


def test_mcp_validation_success_on_second_attempt_returns_success(nl_to_sql_mods, monkeypatch):
    main_mod, shared_mod = nl_to_sql_mods
    observed_queries: list[str] = []
    call_count = {"n": 0}

    def fake_generate_sql_plan(self, *, task_type, query, slots, domain_context):
        observed_queries.append(query)
        return _stub_plan(task_type)

    def fake_execute_query(_session_id, _task_type, query):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return {
                "status": "validation_error",
                "error": {"message": "missing LIMIT"},
                "data": [],
                "source_tables": [],
                "purpose": "analysis",
            }
        return {
            "status": "success",
            "data": [{"category_code": "supermarket", "category_name": "超市", "poi_count": 5}],
            "source_tables": ["app_area_convenience_category_daily"],
            "purpose": "analysis",
            "error": None,
        }

    monkeypatch.setattr(
        main_mod.server.planner,
        "generate_sql_plan",
        MethodType(fake_generate_sql_plan, main_mod.server.planner),
    )
    monkeypatch.setattr(main_mod, "execute_query", fake_execute_query)

    request = _build_request_message(
        shared_mod,
        task_type="neighborhood.convenience_query",
        payload={"domain_user_query": "Astoria 便利设施？", "slots": {"area_id": {"value": "QN0101"}}, "domain_context": {}},
    )
    response = main_mod.server.handle_message(request)
    content = shared_mod.extract_response_content(response)

    assert content["status"] == "success"
    payload = content.get("payload") or {}
    assert payload.get("neighborhood_result", {}).get("status") == "success"
    assert payload.get("executions") and len(payload["executions"]) == 1
    assert len(observed_queries) == 2
    assert "[MCP SQL 校验器返回的错误]" in observed_queries[1]
    assert "missing LIMIT" in observed_queries[1]


def test_inner_llm_retry_exhaustion_returns_llm_sql_plan_retry_exhausted(nl_to_sql_mods, monkeypatch):
    main_mod, shared_mod = nl_to_sql_mods
    from nyc_agent_shared.llm_client import LlmClientError

    call_count = {"n": 0}

    def fake_generate_sql_plan(self, *, task_type, query, slots, domain_context):
        call_count["n"] += 1
        raise LlmClientError("SQL_PLAN_RETRY_EXHAUSTED: invalid JSON")

    def fake_execute_query(*_args, **_kwargs):  # should never be called
        raise AssertionError("execute_query should not run when planner exhausts")

    monkeypatch.setattr(
        main_mod.server.planner,
        "generate_sql_plan",
        MethodType(fake_generate_sql_plan, main_mod.server.planner),
    )
    monkeypatch.setattr(main_mod, "execute_query", fake_execute_query)

    request = _build_request_message(
        shared_mod,
        task_type="neighborhood.convenience_query",
        payload={"domain_user_query": "Astoria 便利？", "slots": {"area_id": {"value": "QN0101"}}, "domain_context": {}},
    )
    response = main_mod.server.handle_message(request)
    content = shared_mod.extract_response_content(response)

    assert content["status"] == "no_data"
    payload = content.get("payload") or {}
    assert payload.get("reason") == "llm_sql_plan_retry_exhausted"
    assert "SQL_PLAN_RETRY_EXHAUSTED" in payload.get("planner_error", "")
    assert payload.get("mcp_retry_attempts") == 1
    assert call_count["n"] == 1


def test_execution_error_short_circuits_without_outer_retry(nl_to_sql_mods, monkeypatch):
    main_mod, shared_mod = nl_to_sql_mods
    observed_queries: list[str] = []

    def fake_generate_sql_plan(self, *, task_type, query, slots, domain_context):
        observed_queries.append(query)
        return _stub_plan(task_type)

    def fake_execute_query(_session_id, _task_type, _query):
        return {
            "status": "execution_error",
            "error": {"message": "connection reset"},
            "data": [],
            "source_tables": [],
            "purpose": "analysis",
        }

    monkeypatch.setattr(
        main_mod.server.planner,
        "generate_sql_plan",
        MethodType(fake_generate_sql_plan, main_mod.server.planner),
    )
    monkeypatch.setattr(main_mod, "execute_query", fake_execute_query)

    request = _build_request_message(
        shared_mod,
        task_type="neighborhood.convenience_query",
        payload={"domain_user_query": "Astoria 便利？", "slots": {"area_id": {"value": "QN0101"}}, "domain_context": {}},
    )
    response = main_mod.server.handle_message(request)
    content = shared_mod.extract_response_content(response)

    assert content["status"] == "dependency_failed"
    assert (content.get("error") or {}).get("code") == "SQL_EXECUTION_FAILED"
    assert len(observed_queries) == 1
