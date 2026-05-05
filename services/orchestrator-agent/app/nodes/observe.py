"""Node 5 — observe + degrade (rule-based).

Reduce the list of agent_results into a single "compose hint" for Node 6:
- any clarification_required → ask_follow_up route
- all success            → respond with merged data
- all no_data            → respond with "no data" message
- any dependency_failed  → respond with degraded message
- any unsupported        → respond with explanation

First cut: only one agent is ever called, so reduction is trivial.
Future cuts: merge multiple agent results for comparison intent.
"""
from __future__ import annotations

from app.state import OrchestratorState


def observe(state: OrchestratorState) -> dict:
    if not state.agent_results:
        return {"final_data_quality": "unknown"}

    sources = [
        {
            "name": result.agent,
            "type": "a2a",
            "task_type": result.task_type,
        }
        for result in state.agent_results
    ]
    quality_map = {
        "success": "reference",
        "no_data": "no_data",
        "dependency_failed": "unknown",
        "unsupported_data_request": "unknown",
        "clarification_required": "unknown",
    }
    statuses = [result.status for result in state.agent_results]
    if all(status == "success" for status in statuses):
        data_quality = "reference"
    elif all(status == "no_data" for status in statuses):
        data_quality = "no_data"
    elif any(status == "success" for status in statuses):
        data_quality = "reference"
    else:
        data_quality = quality_map.get(statuses[0], "unknown")

    return {
        "final_sources": sources,
        "final_data_quality": data_quality,
    }
