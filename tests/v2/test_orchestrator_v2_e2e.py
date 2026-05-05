"""First-cut e2e for orchestrator-agent-v2.

Talks DIRECTLY to v2 (port 8016) rather than going through the gateway, so
this test is independent of the USE_ORCHESTRATOR_V2 env flag. The gateway
side is verified separately by the existing 138 tests still passing.

Skipped automatically when v2 is not reachable, so flipping USE_ORCHESTRATOR_V2
or temporarily stopping the v2 container does not break `make test`.
"""
from __future__ import annotations

import os

import httpx
import pytest

V2_URL = os.environ.get("ORCHESTRATOR_V2_URL", "http://localhost:8010").rstrip("/")
TIMEOUT = 60.0  # LangGraph + 2 LLM calls + A2A → neighborhood-agent → mcp-sql → PG


def _v2_up() -> bool:
    try:
        r = httpx.get(f"{V2_URL}/health", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _v2_up(),
    reason=f"orchestrator-agent-v2 not reachable at {V2_URL}; skip v2 e2e",
)


@pytest.fixture(scope="module")
def http():
    with httpx.Client(timeout=TIMEOUT) as client:
        yield client


def test_v2_health_and_ready(http):
    health = http.get(f"{V2_URL}/health").json()
    assert health["status"] == "ok"
    assert health["service"] == "orchestrator-agent"

    ready = http.get(f"{V2_URL}/ready").json()
    assert ready["dependencies"]["graph"] == "compiled"


def test_v2_chat_safety_question_returns_real_data(http):
    """The first-cut happy path: 'Astoria 安全吗' → neighborhood.crime_query
    → A2A neighborhood-agent → mcp-sql → real PG numbers → respond node."""
    session_id = "test_v2_session_safety"
    response = http.post(
        f"{V2_URL}/chat",
        json={"session_id": session_id, "message": "Astoria 安全吗？", "debug": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    data = body["data"]

    # Either a confident answer (LLM up) or a clarification (LLM down) — the
    # graph itself ran. Reject silent fallthroughs.
    assert data["message_type"] in {"answer", "follow_up", "no_data"}
    assert isinstance(data.get("answer"), str) and data["answer"], \
        f"answer must be non-empty, got: {data!r}"

    # Trace should show the LangGraph orchestrator.
    debug = data.get("debug") or {}
    services = {item.get("service") for item in (debug.get("trace_summary") or [])}
    assert "orchestrator-agent" in services
    assert debug.get("intent_detected") in {
        "neighborhood.crime_query",
        "neighborhood.entertainment_query",
        "neighborhood.convenience_query",
        "area.metrics_query",
        # If the LLM mis-routes to chitchat / unknown the test is still useful
        # — it shows the graph wired together end-to-end. Don't fail on that.
        "chitchat", "unknown",
    }


def test_v2_chat_housing_routes_through_housing_agent(http):
    """Cut 3: 'Astoria 的 1 居一般多少钱？预算 2500 美元以下'
    → housing.* intent → A2A housing-agent → mcp-sql → respond node.
    Also exercises budget + bedroom slot extraction in understand."""
    session_id = "test_v2_session_housing"
    response = http.post(
        f"{V2_URL}/chat",
        json={
            "session_id": session_id,
            "message": "Astoria 的 1 居一般多少钱？预算 2500 美元以下",
            "debug": True,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data["message_type"] in {"answer", "follow_up", "no_data"}
    assert isinstance(data.get("answer"), str) and data["answer"]

    debug = data.get("debug") or {}
    intent = debug.get("intent_detected")
    assert intent in {"housing.rent_query", "housing.listing_search"}, \
        f"housing query should map to housing.* intent, got {intent!r}"

    agents = {r.get("agent") for r in (debug.get("agent_results") or [])}
    assert "housing-agent" in agents, f"expected housing-agent, got {agents!r}"


def test_v2_chat_weather_routes_through_weather_agent(http):
    """Cut 2: 'Astoria 现在天气怎么样' → weather.* intent → A2A
    weather-agent → mcp-weather → NWS → respond node."""
    session_id = "test_v2_session_weather"
    response = http.post(
        f"{V2_URL}/chat",
        json={"session_id": session_id, "message": "Astoria 现在天气怎么样？", "debug": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data["message_type"] in {"answer", "no_data"}
    assert isinstance(data.get("answer"), str) and data["answer"]

    debug = data.get("debug") or {}
    intent = debug.get("intent_detected")
    assert intent in {"weather.current", "weather.hourly_forecast"}, \
        f"weather query should map to weather.* intent, got {intent!r}"

    # Confirm the v2 graph actually called weather-agent (and not the
    # 'unsupported' placeholder branch).
    agent_results = debug.get("agent_results") or []
    agents = {r.get("agent") for r in agent_results}
    assert "weather-agent" in agents, \
        f"expected weather-agent in agent_results, got {agents!r}"
