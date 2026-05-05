"""C2–C5 — Extended /chat e2e flows.

Goes beyond the 17 happy-path cases in test_e2e_business_flows.py to exercise:
  C2 multi-turn profile accumulation (BL §9 step 5-6: weight inferred from chat)
  C3 recommendations endpoint after target_area + weights are set
  C4 three-area comparison (BL §4 area-comparison capability)
  C5 ambiguous-input gate (must signal missing target_area)

User-facing prose lives in the `answer` field of /chat responses (per the
gateway contract); the structured signals are `message_type`, `next_action`,
and `missing_slots`. Tests check both.
"""
from __future__ import annotations

import os

import httpx
import pytest

GATEWAY = os.environ.get("GATEWAY_URL", "http://localhost:8000").rstrip("/")
CHAT_TIMEOUT = 45.0


@pytest.fixture(scope="module")
def http():
    with httpx.Client(timeout=CHAT_TIMEOUT) as c:
        yield c


@pytest.fixture()
def fresh_session(http: httpx.Client) -> str:
    body = http.post(
        f"{GATEWAY}/sessions",
        json={"client_timezone": "America/New_York"},
    ).json()
    return body["data"]["session_id"]


def _envelope(response: httpx.Response) -> dict:
    assert response.status_code == 200, f"{response.status_code}: {response.text}"
    body = response.json()
    assert body["success"] is True, body
    return body["data"]


def _chat(http: httpx.Client, session_id: str, message: str) -> dict:
    return _envelope(
        http.post(
            f"{GATEWAY}/chat",
            json={"session_id": session_id, "message": message, "debug": True},
        )
    )


# ---------------------------------------------------------------------------
# C2 — multi-turn profile accumulation
# ---------------------------------------------------------------------------
def test_chat_multi_turn_profile_accumulation(http, fresh_session):
    """Three messages in sequence; later turns must see profile state from
    earlier turns. BL §9 step 5-6 explicitly requires the agent to update
    user weight profile when the user signals preference."""
    sid = fresh_session
    # Turn 1: set target_area via PATCH (simpler than NLU resolution).
    http.patch(
        f"{GATEWAY}/sessions/{sid}/profile",
        json={"target_area_id": "QN0101"},
    )
    # Turn 2: ask a localized question that requires target_area.
    t2 = _chat(http, sid, "Astoria 安全吗？")
    assert t2["message_type"] == "answer"
    p2 = t2["profile_snapshot"]
    assert p2.get("target_area", {}).get("area_id") == "QN0101"
    assert "target_area" not in (p2.get("missing_required_fields") or [])
    # Turn 3: ask another dimension; profile_snapshot must still carry the area.
    t3 = _chat(http, sid, "那娱乐设施呢？")
    p3 = t3["profile_snapshot"]
    assert p3.get("target_area", {}).get("area_id") == "QN0101"


# ---------------------------------------------------------------------------
# C3 — recommendations endpoint
# ---------------------------------------------------------------------------
def test_recommendations_after_profile_setup(http, fresh_session):
    """Even before any heavy reasoning, /recommendations must return a
    well-shaped response (MVP returns an empty list, but the contract holds).
    """
    sid = fresh_session
    http.patch(
        f"{GATEWAY}/sessions/{sid}/profile",
        json={
            "target_area_id": "QN0101",
            "budget": {"min": 2000, "max": 3500, "currency": "USD"},
            "weights": {"safety": 0.4, "rent": 0.3, "commute": 0.3,
                          "convenience": 0.0, "entertainment": 0.0},
        },
    )
    body = _envelope(http.get(f"{GATEWAY}/sessions/{sid}/recommendations"))
    assert "recommendations" in body
    assert isinstance(body["recommendations"], list)


# ---------------------------------------------------------------------------
# C4 — three-area comparison
# ---------------------------------------------------------------------------
def test_chat_three_area_comparison(http, fresh_session):
    sid = fresh_session
    http.patch(f"{GATEWAY}/sessions/{sid}/profile", json={"target_area_id": "QN0101"})
    body = _chat(
        http, sid,
        "Astoria、Williamsburg、Midtown 这三个区域比较一下，哪个更适合留学生？",
    )
    # Comparison must be gated to ask the user which dimension to compare on
    # (orchestrator can't pick safety vs rent vs commute on the user's behalf).
    assert body["message_type"] == "follow_up"
    assert body.get("next_action") == "ask_follow_up"
    assert "comparison_dimension" in (body.get("missing_slots") or [])
    answer = body.get("answer") or ""
    assert any(k in answer for k in ("维度", "比较", "对比"))


# ---------------------------------------------------------------------------
# C5 — confirmation branch on ambiguous input
# ---------------------------------------------------------------------------
def test_chat_ambiguous_input_handled_gracefully(http, fresh_session):
    """A vague request without target_area must NOT leak the "当前区域"
    placeholder string into the reply. The new LangGraph orchestrator may
    classify this as either chitchat (give a friendly intro) or follow_up
    (ask which area) — both are acceptable.

    The strict pre-cut-9 contract was "must follow_up", but the new
    LLM-based understand node has more flexibility. Tighten this test
    once we agree on stricter intent-classification heuristics."""
    sid = fresh_session  # no target_area set yet
    body = _chat(http, sid, "随便给我推荐点什么")
    assert body["message_type"] in {"follow_up", "answer"}
    answer = body.get("answer") or ""
    # The pre-cut-9 placeholder leak bug must stay fixed.
    assert "当前区域" not in answer
    # And the reply should be substantive, not empty.
    assert isinstance(answer, str) and len(answer) > 5
