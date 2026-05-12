"""Node 1 — backfill hook.

LangGraph checkpoints keep conversation-local working memory, while
mcp-profile stores the canonical session profile used by the gateway and UI.
Backfill bridges those two stores at the start of each turn so short follow-up
queries ("那便利呢？") can use the profile's current target_area.
"""
from __future__ import annotations

import logging

from app.a2a_adapter import call_agent
from app.state import OrchestratorState

logger = logging.getLogger(__name__)


def _target_area_from_profile(snapshot: dict) -> tuple[str | None, str | None]:
    area = snapshot.get("target_area") if isinstance(snapshot, dict) else None
    area_id = snapshot.get("target_area_id") if isinstance(snapshot, dict) else None
    area_name = None
    if isinstance(area, dict):
        area_id = area.get("area_id") or area_id
        area_name = area.get("area_name")
    return (
        str(area_id).strip() if area_id else None,
        str(area_name).strip() if area_name else None,
    )


def backfill(state: OrchestratorState) -> dict:
    if not state.session_id:
        return {}
    try:
        response = call_agent(
            "profile",
            task_type="profile.get_snapshot",
            session_id=state.session_id,
            payload={},
            trace_id=state.trace_id,
        )
    except Exception as exc:
        logger.warning("profile backfill failed for session=%s: %s", state.session_id, exc)
        return {}

    if response.get("status") != "success":
        return {}
    snapshot = (response.get("payload") or {}).get("profile_snapshot") or {}
    area_id, area_name = _target_area_from_profile(snapshot)
    update: dict[str, str] = {}
    if area_id and not state.target_area_id:
        update["target_area_id"] = area_id
    if area_name and not state.target_area_name:
        update["target_area_name"] = area_name
    return update
