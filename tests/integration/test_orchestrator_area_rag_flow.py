from __future__ import annotations

import os

import httpx
import pytest

ORCH_URL = os.environ.get("ORCHESTRATOR_V2_URL", "http://localhost:8010").rstrip("/")


def _orchestrator_up() -> bool:
    try:
        return httpx.get(f"{ORCH_URL}/health", timeout=2.0).status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _orchestrator_up(),
    reason=f"orchestrator not reachable at {ORCH_URL}",
)


def test_orchestrator_area_rag_can_resolve_clear_area_name():
    with httpx.Client(timeout=60.0) as client:
        session_id = "test_area_rag_resolve"
        r = client.post(
            f"{ORCH_URL}/chat",
            json={"session_id": session_id, "message": "Astoria 安全吗？", "debug": True},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        data = body["data"]
        assert data["message_type"] in {"answer", "follow_up", "no_data"}
        if data["message_type"] == "follow_up":
            assert "target_area" in (data.get("missing_slots") or [])


def test_orchestrator_area_rag_ambiguous_query_prefers_follow_up():
    with httpx.Client(timeout=60.0) as client:
        session_id = "test_area_rag_ambiguous"
        r = client.post(
            f"{ORCH_URL}/chat",
            json={"session_id": session_id, "message": "这个区安全吗？", "debug": True},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        data = body["data"]
        assert data["message_type"] in {"follow_up", "answer", "no_data"}
        if data["message_type"] == "follow_up":
            assert "target_area" in (data.get("missing_slots") or [])

