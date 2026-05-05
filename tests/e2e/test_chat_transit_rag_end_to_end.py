from __future__ import annotations

import os

import httpx
import pytest

GATEWAY = os.environ.get("GATEWAY_URL", "http://localhost:8000").rstrip("/")


def _gateway_up() -> bool:
    try:
        return httpx.get(f"{GATEWAY}/health", timeout=2.0).status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _gateway_up(), reason=f"gateway not reachable at {GATEWAY}")


def _create_session(client: httpx.Client) -> str:
    r = client.post(f"{GATEWAY}/sessions", json={"client_timezone": "America/New_York"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    return body["data"]["session_id"]


def test_chat_transit_natural_language_can_execute():
    with httpx.Client(timeout=60.0) as client:
        session_id = _create_session(client)
        r = client.post(
            f"{GATEWAY}/chat",
            json={
                "session_id": session_id,
                "message": "从 Astoria 到 NYU 坐地铁大概多久？",
                "debug": True,
            },
        )
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["message_type"] in {"answer", "follow_up", "no_data"}
        assert isinstance(data.get("answer"), str) and data["answer"]


def test_chat_transit_missing_endpoints_triggers_clarification():
    with httpx.Client(timeout=60.0) as client:
        session_id = _create_session(client)
        r = client.post(
            f"{GATEWAY}/chat",
            json={
                "session_id": session_id,
                "message": "通勤多久？",
                "debug": True,
            },
        )
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["message_type"] in {"follow_up", "answer", "no_data"}
        if data["message_type"] == "follow_up":
            assert data["next_action"] == "ask_follow_up"

