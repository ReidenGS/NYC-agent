"""LangGraph wiring — 6 nodes per docs/AI_Agent_Business_Logic.md §13.1.

Topology:
  backfill → understand → persist → gate
                                       ├─ missing slots → respond (ask)
                                       └─ all set      → plan_execute → observe → respond (answer)
                                                                                        |
                                                                                       END
"""
from __future__ import annotations

import logging
from typing import Literal

from langgraph.graph import END, START, StateGraph

from app.nodes.backfill import backfill
from app.nodes.gate import gate
from app.nodes.observe import observe
from app.nodes.persist import persist
from app.nodes.plan_execute import plan_execute
from app.nodes.respond import respond
from app.nodes.understand import understand
from app.state import OrchestratorState

logger = logging.getLogger(__name__)


def _route_after_gate(state: OrchestratorState) -> Literal["plan_execute", "respond"]:
    return "respond" if state.final_missing_slots else "plan_execute"


def build_graph(checkpointer=None):
    """Assemble and compile the orchestrator graph. `checkpointer` may be None
    in test contexts; production passes PostgresSaver."""
    builder = StateGraph(OrchestratorState)

    builder.add_node("backfill", backfill)
    builder.add_node("understand", understand)
    builder.add_node("persist", persist)
    builder.add_node("gate", gate)
    builder.add_node("plan_execute", plan_execute)
    builder.add_node("observe", observe)
    builder.add_node("respond", respond)

    builder.add_edge(START, "backfill")
    builder.add_edge("backfill", "understand")
    builder.add_edge("understand", "persist")
    builder.add_edge("persist", "gate")
    builder.add_conditional_edges(
        "gate",
        _route_after_gate,
        {"plan_execute": "plan_execute", "respond": "respond"},
    )
    builder.add_edge("plan_execute", "observe")
    builder.add_edge("observe", "respond")
    builder.add_edge("respond", END)

    return builder.compile(checkpointer=checkpointer)
