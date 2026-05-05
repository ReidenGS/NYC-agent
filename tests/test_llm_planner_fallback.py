from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]


def import_service_planner(service_name: str):
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
    service_path = str(REPO_ROOT / "services" / service_name)
    shared_path = str(REPO_ROOT / "shared")
    sys.path.insert(0, service_path)
    sys.path.insert(0, shared_path)
    return importlib.import_module("app.llm_planner")


class SelectStarClient:
    def __init__(self, **_: Any) -> None:
        pass

    def generate_json(self, *, system_prompt: str, user_payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "sql_ready",
            "housing_result_type": "rent_range",
            "queries": [
                {
                    "purpose": "analysis",
                    "execute_when": "always",
                    "expected_result": "bad_query",
                    "sql": "SELECT * FROM app_area_rental_market_daily LIMIT 1",
                    "params": {},
                }
            ],
        }


class MissingLimitClient:
    def __init__(self, **_: Any) -> None:
        pass

    def generate_json(self, *, system_prompt: str, user_payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "sql_ready",
            "neighborhood_result_type": "crime_breakdown",
            "queries": [
                {
                    "purpose": "analysis",
                    "execute_when": "always",
                    "expected_result": "bad_query",
                    "domain": "safety",
                    "sql": "SELECT area_id FROM v_area_metrics_latest",
                    "params": {},
                }
            ],
        }


def test_housing_llm_planner_falls_back_when_sql_is_rejected(monkeypatch) -> None:
    planner = import_service_planner("housing-agent")
    monkeypatch.setattr(planner.settings, "use_llm_sql_planner", True)
    monkeypatch.setattr(planner.settings, "openai_api_key", "test-key")
    monkeypatch.setattr(planner, "JsonLlmClient", SelectStarClient)

    plan = planner.build_plan(
        "housing.rent_query",
        "Astoria 的 1b 租金多少？",
        {"area_id": {"value": "QN0101"}, "area_name": {"value": "Astoria"}, "bedroom_type": {"value": "1br"}},
        {},
    )

    assert plan["planner_mode"] == "deterministic_fallback"
    assert "SELECT *" in plan["planner_fallback_reason"]
    assert "select *" not in plan["queries"][0]["sql"].lower()


def test_neighborhood_llm_planner_falls_back_when_limit_missing(monkeypatch) -> None:
    planner = import_service_planner("neighborhood-agent")
    monkeypatch.setattr(planner.settings, "use_llm_sql_planner", True)
    monkeypatch.setattr(planner.settings, "openai_api_key", "test-key")
    monkeypatch.setattr(planner, "JsonLlmClient", MissingLimitClient)

    plan = planner.build_plan(
        "neighborhood.crime_query",
        "Astoria 偷窃数量是多少？",
        {"area_id": {"value": "QN0101"}, "area_name": {"value": "Astoria"}},
        {},
    )

    assert plan["planner_mode"] == "deterministic_fallback"
    assert "missing LIMIT" in plan["planner_fallback_reason"]
    assert all("limit" in query["sql"].lower() for query in plan["queries"])
