"""Unit coverage for orchestrator follow-up memory and response metadata.

These tests pin the agreed behavior:
- pending follow-ups are stored as session memory, not thrown away;
- the understand LLM can use that pending context to resolve short answers;
- respond emits natural language while routing metadata is assigned by code.
"""
from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage

from tests.conftest import add_service_to_path


@pytest.fixture(autouse=True)
def _orchestrator_path():
    add_service_to_path("orchestrator-agent")


def _fake_llm_with_json(payload: dict):
    class FakeLLM:
        def invoke(self, _messages):
            return AIMessage(content=json.dumps(payload))

    return FakeLLM()


def test_gate_writes_complete_pending_followup():
    from app.nodes.gate import gate
    from app.state import OrchestratorState, PendingFollowUp

    state = OrchestratorState(
        current_user_message="房租怎么样？",
        intent="housing.rent_query",
        constraints={"bedroom_type": "1br"},
    )

    update = gate(state)

    assert update["final_missing_slots"] == ["target_area"]
    pending = update["pending_follow_up"]
    assert isinstance(pending, PendingFollowUp)
    assert pending.asked_slot == "target_area"
    assert pending.asked_intent == "housing.rent_query"
    assert pending.missing_slots == ["target_area"]
    assert pending.original_user_query == "房租怎么样？"
    assert pending.partial_constraints == {"bedroom_type": "1br"}
    assert pending.asked_at


def test_backfill_preserves_pending_followup():
    from app.nodes import backfill as backfill_mod
    from app.nodes.backfill import backfill
    from app.state import OrchestratorState, PendingFollowUp

    def fake_call_agent(*_args, **_kwargs):
        raise AssertionError("profile should not be called without session_id")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(backfill_mod, "call_agent", fake_call_agent)
    pending = PendingFollowUp(
        asked_slot="target_area",
        asked_intent="housing.rent_query",
        asked_at="2026-04-29T12:00:00+00:00",
        missing_slots=["target_area"],
        original_user_query="房租怎么样？",
    )
    state = OrchestratorState(current_user_message="Astoria", pending_follow_up=pending)

    assert backfill(state) == {}
    monkeypatch.undo()


def test_backfill_loads_target_area_from_profile(monkeypatch):
    from app.nodes import backfill as backfill_mod
    from app.nodes.backfill import backfill
    from app.state import OrchestratorState

    monkeypatch.setattr(
        backfill_mod,
        "call_agent",
        lambda *_args, **_kwargs: {
            "status": "success",
            "payload": {
                "profile_snapshot": {
                    "target_area_id": "MN0101",
                    "target_area": {
                        "area_id": "MN0101",
                        "area_name": "Financial District-Battery Park City",
                    },
                }
            },
        },
    )

    update = backfill(OrchestratorState(session_id="sess_1"))

    assert update == {
        "target_area_id": "MN0101",
        "target_area_name": "Financial District-Battery Park City",
    }


def test_backfill_does_not_override_graph_target_area(monkeypatch):
    from app.nodes import backfill as backfill_mod
    from app.nodes.backfill import backfill
    from app.state import OrchestratorState

    monkeypatch.setattr(
        backfill_mod,
        "call_agent",
        lambda *_args, **_kwargs: {
            "status": "success",
            "payload": {
                "profile_snapshot": {
                    "target_area_id": "MN0101",
                    "target_area": {
                        "area_id": "MN0101",
                        "area_name": "Financial District-Battery Park City",
                    },
                }
            },
        },
    )

    update = backfill(
        OrchestratorState(
            session_id="sess_1",
            target_area_id="QN0101",
            target_area_name="Astoria",
        )
    )

    assert update == {}


def test_understand_uses_pending_to_fill_missing_area(monkeypatch):
    from app.nodes import understand as understand_mod
    from app.nodes.understand import understand
    from app.state import OrchestratorState, PendingFollowUp

    monkeypatch.setattr(understand_mod.settings, "openai_api_key", "test-key")
    monkeypatch.setattr(
        understand_mod,
        "_build_llm",
        lambda: _fake_llm_with_json(
            {
                "intent": "housing.rent_query",
                "detected_areas": [
                    {
                        "area_id": "QN0101",
                        "area_name": "Astoria",
                        "source": "user_explicit",
                    }
                ],
                "constraints": {},
                "persistable_field_updates": {},
                "confidence": 0.95,
            }
        ),
    )
    pending = PendingFollowUp(
        asked_slot="target_area",
        asked_intent="housing.rent_query",
        asked_at="2026-04-29T12:00:00+00:00",
        missing_slots=["target_area"],
        original_user_query="房租怎么样？",
    )
    state = OrchestratorState(current_user_message="Astoria", pending_follow_up=pending)

    update = understand(state)

    assert update["intent"] == "housing.rent_query"
    assert update["target_area_id"] == "QN0101"
    assert update["target_area_name"] == "Astoria"
    assert update["pending_follow_up"] is None


def test_understand_rag_resolves_leading_area_phrase_when_llm_misses_area(monkeypatch):
    from app.nodes import understand as understand_mod
    from app.nodes.understand import understand
    from app.state import OrchestratorState

    class FakeResolver:
        def resolve(self, query_text):
            assert query_text == "Financial District-Battery Park City"
            return type(
                "Result",
                (),
                {
                    "resolved": True,
                    "area_id": "MN0101",
                    "area_name": "Financial District-Battery Park City",
                    "score": 1.0,
                    "candidates": [],
                },
            )()

    monkeypatch.setattr(understand_mod.settings, "openai_api_key", "test-key")
    monkeypatch.setattr(understand_mod, "get_area_resolver", lambda: FakeResolver())
    monkeypatch.setattr(
        understand_mod,
        "_build_llm",
        lambda: _fake_llm_with_json(
            {
                "intent": "neighborhood.convenience_query",
                "detected_areas": [],
                "constraints": {},
                "persistable_field_updates": {},
                "confidence": 0.8,
            }
        ),
    )

    update = understand(
        OrchestratorState(
            current_user_message="Financial District-Battery Park City 有什么便利设施"
        )
    )

    assert update["target_area_id"] == "MN0101"
    assert update["target_area_name"] == "Financial District-Battery Park City"


def test_understand_explicit_wall_street_overrides_existing_area(monkeypatch):
    from app.nodes import understand as understand_mod
    from app.nodes.understand import understand
    from app.state import OrchestratorState

    monkeypatch.setattr(understand_mod.settings, "openai_api_key", "")

    update = understand(
        OrchestratorState(
            current_user_message="华尔街地区的安全情况怎么样？请给我犯罪数据。",
            target_area_id="QN0103",
            target_area_name="Astoria (Central)",
        )
    )

    assert update["intent"] == "neighborhood.crime_query"
    assert update["target_area_id"] == "MN0101"
    assert update["target_area_name"] == "Financial District-Battery Park City"


def test_understand_explicit_lic_overrides_existing_area(monkeypatch):
    from app.nodes import understand as understand_mod
    from app.nodes.understand import understand
    from app.state import OrchestratorState

    monkeypatch.setattr(understand_mod.settings, "openai_api_key", "")

    update = understand(
        OrchestratorState(
            current_user_message="Long Island City 的安全情况怎么样？",
            target_area_id="QN0103",
            target_area_name="Astoria (Central)",
        )
    )

    assert update["intent"] == "neighborhood.crime_query"
    assert update["target_area_id"] == "QN0201"
    assert update["target_area_name"] == "Long Island City-Hunters Point"


def test_understand_ambiguous_area_answer_reuses_pending_intent(monkeypatch):
    from app.nodes import understand as understand_mod
    from app.nodes.understand import understand
    from app.state import OrchestratorState, PendingFollowUp

    monkeypatch.setattr(understand_mod.settings, "openai_api_key", "test-key")
    monkeypatch.setattr(
        understand_mod,
        "_build_llm",
        lambda: _fake_llm_with_json(
            {
                "intent": "unknown",
                "detected_areas": [
                    {
                        "area_id": "QN0101",
                        "area_name": "Astoria",
                        "source": "user_explicit",
                    }
                ],
                "constraints": {},
                "persistable_field_updates": {},
                "confidence": 0.6,
            }
        ),
    )
    pending = PendingFollowUp(
        asked_slot="target_area",
        asked_intent="housing.rent_query",
        asked_at="2026-04-29T12:00:00+00:00",
        missing_slots=["target_area"],
        original_user_query="房租怎么样？",
    )
    state = OrchestratorState(current_user_message="Astoria", pending_follow_up=pending)

    update = understand(state)

    assert update["intent"] == "housing.rent_query"
    assert update["target_area_id"] == "QN0101"
    assert update["pending_follow_up"] is None


def test_understand_clears_pending_on_clear_topic_switch(monkeypatch):
    from app.nodes import understand as understand_mod
    from app.nodes.understand import understand
    from app.state import OrchestratorState, PendingFollowUp

    monkeypatch.setattr(understand_mod.settings, "openai_api_key", "test-key")
    monkeypatch.setattr(
        understand_mod,
        "_build_llm",
        lambda: _fake_llm_with_json(
            {
                "intent": "weather.current",
                "detected_areas": [
                    {
                        "area_id": "QN0101",
                        "area_name": "Astoria",
                        "source": "user_explicit",
                    }
                ],
                "constraints": {"target_time": "current"},
                "persistable_field_updates": {},
                "confidence": 0.92,
            }
        ),
    )
    pending = PendingFollowUp(
        asked_slot="target_area",
        asked_intent="housing.rent_query",
        asked_at="2026-04-29T12:00:00+00:00",
        missing_slots=["target_area"],
        original_user_query="房租怎么样？",
    )
    state = OrchestratorState(
        current_user_message="今天 Astoria 会下雨吗？",
        pending_follow_up=pending,
    )

    update = understand(state)

    assert update["intent"] == "weather.current"
    assert update["pending_follow_up"] is None


def test_respond_domain_clarification_writes_pending(monkeypatch):
    from app.nodes import respond as respond_mod
    from app.nodes.respond import respond
    from app.state import AgentResult, OrchestratorState, PendingFollowUp

    monkeypatch.setattr(respond_mod.settings, "openai_api_key", "")
    state = OrchestratorState(
        current_user_message="下一班地铁什么时候来？",
        intent="transit.next_departure",
        agent_results=[
            AgentResult(
                agent="transit-agent",
                task_type="transit.next_departure",
                status="clarification_required",
                payload={
                    "missing_slots": ["route_id", "stop_name"],
                    "clarification": "你想查哪条线路、哪个站？",
                },
            )
        ],
    )

    update = respond(state)

    assert update["final_message_type"] == "follow_up"
    assert update["final_next_action"] == "ask_follow_up"
    assert update["final_missing_slots"] == ["route_id", "stop_name"]
    pending = update["pending_follow_up"]
    assert isinstance(pending, PendingFollowUp)
    assert pending.asked_slot == "route_id"
    assert pending.asked_intent == "transit.next_departure"
    assert pending.missing_slots == ["route_id", "stop_name"]
    assert pending.prompt_text == "你想查哪条线路、哪个站？"
    assert pending.original_user_query == "下一班地铁什么时候来？"


def test_respond_llm_outputs_text_metadata_stays_deterministic(monkeypatch):
    from app.nodes import respond as respond_mod
    from app.nodes.respond import respond
    from app.state import AgentResult, OrchestratorState

    class FakeChatOpenAI:
        def __init__(self, **_kwargs):
            pass

        def invoke(self, _messages):
            return AIMessage(content="你想查哪条线路、哪个站？")

    monkeypatch.setattr(respond_mod.settings, "openai_api_key", "test-key")
    monkeypatch.setattr(respond_mod, "ChatOpenAI", FakeChatOpenAI)
    state = OrchestratorState(
        current_user_message="下一班地铁什么时候来？",
        intent="transit.next_departure",
        agent_results=[
            AgentResult(
                agent="transit-agent",
                task_type="transit.next_departure",
                status="clarification_required",
                payload={"missing_slots": ["route_id", "stop_name"]},
            )
        ],
    )

    update = respond(state)

    assert update["final_answer"] == "你想查哪条线路、哪个站？"
    assert not update["final_answer"].lstrip().startswith("{")
    assert update["final_message_type"] == "follow_up"
    assert update["final_next_action"] == "ask_follow_up"
    assert update["final_missing_slots"] == ["route_id", "stop_name"]


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("success", ("answer", "respond_final", [])),
        ("no_data", ("no_data", "respond_final", [])),
        ("unsupported_data_request", ("unsupported", "respond_final", [])),
        ("validation_failed", ("unsupported", "respond_final", [])),
        ("dependency_failed", ("error", "error", [])),
        ("error", ("error", "error", [])),
    ],
)
def test_response_metadata_maps_agent_statuses(status, expected):
    from app.nodes.respond import _response_metadata
    from app.state import AgentResult, OrchestratorState

    state = OrchestratorState(
        agent_results=[
            AgentResult(
                agent="nl-to-sql-agent",
                task_type="housing.rent_query",
                status=status,
                payload={},
            )
        ],
    )

    assert _response_metadata(state) == expected


def test_response_metadata_maps_clarification_required():
    from app.nodes.respond import _response_metadata
    from app.state import AgentResult, OrchestratorState

    state = OrchestratorState(
        agent_results=[
            AgentResult(
                agent="transit-agent",
                task_type="transit.next_departure",
                status="clarification_required",
                payload={"missing_slots": ["route_id", "stop_name"]},
            )
        ],
    )

    assert _response_metadata(state) == (
        "follow_up",
        "ask_follow_up",
        ["route_id", "stop_name"],
    )
