from __future__ import annotations

import importlib
from types import MethodType

from tests.conftest import add_service_to_path


def _build_request_message(shared_mod, *, task_type: str, payload: dict):
    return shared_mod.build_request_message(
        task_type=task_type,
        payload=payload,
        trace_id="trace_test_sql_retry",
        session_id="sess_test_sql_retry",
        source_agent="orchestrator-agent",
        target_agent="housing-agent",
    )


def test_housing_mcp_validation_error_retries_three_times_then_no_data(monkeypatch):
    add_service_to_path("housing-agent")
    main_mod = importlib.import_module("app.main")
    shared_mod = importlib.import_module("nyc_agent_shared.a2a_protocol")

    observed_queries: list[str] = []

    def fake_generate_sql_plan(self, *, task_type, query, slots, domain_context):
        observed_queries.append(query)
        return {
            "status": "sql_ready",
            "queries": [
                {
                    "purpose": "analysis",
                    "execute_when": "always",
                    "expected_result": "x",
                    "sql": "SELECT 1 LIMIT 1",
                    "params": {},
                }
            ],
        }

    def fake_execute_query(_session_id, _query):
        return {
            "status": "validation_error",
            "error": {"message": "forbidden table"},
            "data": None,
            "source_tables": [],
        }

    monkeypatch.setattr(main_mod.server, "generate_sql_plan", MethodType(fake_generate_sql_plan, main_mod.server))
    monkeypatch.setattr(main_mod, "execute_query", fake_execute_query)

    request = _build_request_message(
        shared_mod,
        task_type="housing.rent_query",
        payload={"domain_user_query": "Astoria rent?", "slots": {"area_id": {"value": "QN0101"}}, "domain_context": {}},
    )
    response = main_mod.server.handle_message(request)
    content = shared_mod.extract_response_content(response)

    assert content["status"] == "no_data"
    assert (content.get("payload") or {}).get("reason") == "mcp_sql_validation_retry_exhausted"
    assert len(observed_queries) == 3
    assert "[MCP SQL 校验器返回的错误]" in observed_queries[1]


def test_neighborhood_mcp_validation_error_retries_three_times_then_no_data(monkeypatch):
    add_service_to_path("neighborhood-agent")
    main_mod = importlib.import_module("app.main")
    shared_mod = importlib.import_module("nyc_agent_shared.a2a_protocol")

    observed_queries: list[str] = []

    def fake_generate_sql_plan(self, *, task_type, query, slots, domain_context):
        observed_queries.append(query)
        return {
            "status": "sql_ready",
            "queries": [
                {
                    "purpose": "analysis",
                    "domain": "safety",
                    "execute_when": "always",
                    "expected_result": "x",
                    "sql": "SELECT 1 LIMIT 1",
                    "params": {},
                }
            ],
        }

    def fake_execute_query(_session_id, _query, **_kwargs):
        return {
            "status": "validation_error",
            "error": {"message": "missing LIMIT"},
            "data": None,
            "source_tables": [],
            "domain": "safety",
        }

    monkeypatch.setattr(main_mod.server, "generate_sql_plan", MethodType(fake_generate_sql_plan, main_mod.server))
    monkeypatch.setattr(main_mod, "execute_query", fake_execute_query)

    request = _build_request_message(
        shared_mod,
        task_type="neighborhood.crime_query",
        payload={"domain_user_query": "Astoria crime?", "slots": {"area_id": {"value": "QN0101"}}, "domain_context": {}},
    )
    response = main_mod.server.handle_message(request)
    content = shared_mod.extract_response_content(response)

    assert content["status"] == "no_data"
    assert (content.get("payload") or {}).get("reason") == "mcp_sql_validation_retry_exhausted"
    assert len(observed_queries) == 3
    assert "[MCP SQL 校验器返回的错误]" in observed_queries[1]

