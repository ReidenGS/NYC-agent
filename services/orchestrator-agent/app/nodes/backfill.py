"""Node 1 — backfill hook.

Follow-up interpretation is handled by the understand LLM with access to
LangGraph checkpointed state. This hook intentionally preserves
pending_follow_up so the LLM can see the previous question and missing slots.
"""
from __future__ import annotations

from app.state import OrchestratorState


def backfill(state: OrchestratorState) -> dict:
    return {}
