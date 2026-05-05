"""LangGraph OrchestratorState — Pydantic v2 BaseModel.

Per docs/NYC_Agent_Backend_Tech_Framework.md §2.1, this state IS the
session's working memory. It's checkpointed automatically by PostgresSaver
keyed on thread_id (= session_id), so consecutive /chat calls in the same
session see the full message history without any explicit load.

mcp-profile is NOT loaded into state at the start of every turn; it's only
written when persistable_field_updates fires (see §13.2).
"""
from __future__ import annotations

from typing import Annotated, Any, Literal

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


class DetectedArea(BaseModel):
    area_id: str | None = None
    area_name: str | None = None
    source: Literal["user_explicit", "session_memory", "llm_inferred", "rag_resolved"] = "user_explicit"


class PendingFollowUp(BaseModel):
    asked_slot: str
    asked_intent: str | None = None
    asked_at: str  # ISO timestamp
    prompt_text: str | None = None
    missing_slots: list[str] = Field(default_factory=list)
    original_user_query: str | None = None
    partial_constraints: dict[str, Any] = Field(default_factory=dict)


class AgentResult(BaseModel):
    """A single A2A call's outcome — collected by Node 4 (plan_and_execute)."""
    agent: str
    task_type: str
    status: str  # success / no_data / clarification_required / dependency_failed / unsupported_data_request
    payload: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | None = None


class OrchestratorState(BaseModel):
    # ---- auto-managed by add_messages reducer ----
    messages: Annotated[list[AnyMessage], add_messages] = Field(default_factory=list)

    # ---- request-scope, supplied per /chat ----
    session_id: str | None = None
    trace_id: str | None = None
    debug: bool = False

    # ---- session working state, persisted via checkpointer across turns ----
    target_area_id: str | None = None
    target_area_name: str | None = None
    pending_follow_up: PendingFollowUp | None = None

    # ---- per-turn working values, reset each invoke ----
    current_user_message: str = ""
    intent: str | None = None
    detected_areas: list[DetectedArea] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)
    persistable_field_updates: dict[str, Any] = Field(default_factory=dict)

    agent_results: list[AgentResult] = Field(default_factory=list)

    # ---- final response, set by Node 6 ----
    final_message_type: str = "answer"
    final_answer: str = ""
    final_next_action: str = "respond_final"
    final_missing_slots: list[str] = Field(default_factory=list)
    final_sources: list[dict[str, Any]] = Field(default_factory=list)
    final_data_quality: str = "reference"

    class Config:
        arbitrary_types_allowed = True
