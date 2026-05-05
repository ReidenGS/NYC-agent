from __future__ import annotations

import os

import httpx
import pytest

ORCH_URL = os.environ.get("ORCHESTRATOR_V2_URL", "http://localhost:8010").rstrip("/")


def _up() -> bool:
    try:
        return httpx.get(f"{ORCH_URL}/health", timeout=2.0).status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _up(), reason=f"orchestrator not reachable at {ORCH_URL}")


def test_transit_query_with_named_endpoints_is_executable():
    with httpx.Client(timeout=60.0) as client:
        r = client.post(
            f"{ORCH_URL}/chat",
            json={
                "session_id": "test_transit_rag_exec",
                "message": "从 Astoria Blvd 到 Times Sq 地铁通勤要多久？",
                "debug": True,
            },
        )
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["message_type"] in {"answer", "no_data", "follow_up"}
        debug = data.get("debug") or {}
        intent = debug.get("intent_detected")
        assert intent in {"transit.realtime_commute", "transit.next_departure", "unknown"}


def test_transit_ambiguous_stop_prefers_clarification_or_candidates():
    with httpx.Client(timeout=60.0) as client:
        r = client.post(
            f"{ORCH_URL}/chat",
            json={
                "session_id": "test_transit_rag_ambiguous",
                "message": "下一班从 central 去 downtown 的地铁",
                "debug": True,
            },
        )
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["message_type"] in {"follow_up", "answer", "no_data"}
        if data["message_type"] == "follow_up":
            assert data["next_action"] == "ask_follow_up"

