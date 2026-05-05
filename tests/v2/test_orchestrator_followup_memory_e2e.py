"""Live v2 tests for session-scoped follow-up memory.

These hit the running orchestrator-agent directly. They are skipped when the
service is not available, matching the existing v2 e2e style.
"""
from __future__ import annotations

import os
import uuid

import httpx
import pytest

V2_URL = os.environ.get("ORCHESTRATOR_V2_URL", "http://localhost:8010").rstrip("/")
TIMEOUT = 60.0


def _v2_up() -> bool:
    try:
        response = httpx.get(f"{V2_URL}/health", timeout=2.0)
        return response.status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _v2_up(),
    reason=f"orchestrator-agent-v2 not reachable at {V2_URL}; skip follow-up e2e",
)


@pytest.fixture(scope="module")
def http():
    with httpx.Client(timeout=TIMEOUT) as client:
        yield client


def _session(prefix: str) -> str:
    return f"test_{prefix}_{uuid.uuid4().hex}"


def _chat(http: httpx.Client, session_id: str, message: str) -> dict:
    response = http.post(
        f"{V2_URL}/chat",
        json={"session_id": session_id, "message": message, "debug": True},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True, body
    data = body["data"]
    assert isinstance(data.get("answer"), str) and data["answer"], data
    return data


def _agents(data: dict) -> set[str]:
    debug = data.get("debug") or {}
    return {item.get("agent") for item in (debug.get("agent_results") or [])}


def test_two_turn_missing_area_then_fill_routes_original_housing_intent(http):
    session_id = _session("followup_housing")

    first = _chat(http, session_id, "房租怎么样？")
    assert first["message_type"] == "follow_up"
    assert "target_area" in (first.get("missing_slots") or [])

    second = _chat(http, session_id, "Astoria")
    debug = second.get("debug") or {}

    assert second["message_type"] in {"answer", "no_data"}
    assert debug.get("intent_detected") in {
        "housing.rent_query",
        "housing.listing_search",
    }
    assert "housing-agent" in _agents(second)
    assert "target_area" not in (second.get("missing_slots") or [])


def test_pending_is_cleared_when_user_switches_topic(http):
    session_id = _session("followup_switch")

    first = _chat(http, session_id, "房租怎么样？")
    assert first["message_type"] == "follow_up"
    assert "target_area" in (first.get("missing_slots") or [])

    second = _chat(http, session_id, "今天 Astoria 会下雨吗？")
    debug = second.get("debug") or {}

    assert second["message_type"] in {"answer", "no_data"}
    assert debug.get("intent_detected") in {
        "weather.current",
        "weather.hourly_forecast",
    }
    agents = _agents(second)
    assert "weather-agent" in agents
    assert "housing-agent" not in agents


def test_pending_followup_memory_is_session_scoped(http):
    session_a = _session("followup_a")
    session_b = _session("followup_b")

    first = _chat(http, session_a, "房租怎么样？")
    assert first["message_type"] == "follow_up"
    assert "target_area" in (first.get("missing_slots") or [])

    second = _chat(http, session_b, "Astoria")
    debug = second.get("debug") or {}

    assert debug.get("intent_detected") not in {
        "housing.rent_query",
        "housing.listing_search",
    }
    assert "housing-agent" not in _agents(second)
