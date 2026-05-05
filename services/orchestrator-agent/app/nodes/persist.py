"""Node 2.5 — persist (conditional, A2A → mcp-profile).

Schema-driven: any field in persistable_field_updates that maps to a
known column on app_session_profile gets pushed via profile.patch_slots.
First cut sends them all in one call. Failures are logged but never block
graph progress.
"""
from __future__ import annotations

import logging

from app.a2a_adapter import call_agent
from app.state import OrchestratorState

logger = logging.getLogger(__name__)

# Whitelist of persistable keys mirrors app_session_profile schema. Adding a
# column requires adding a key here and updating the prompt in understand.py.
PERSISTABLE_KEYS = {
    "target_area_id",
    "budget",
    "bedroom_type",
    "target_destination",
    "max_commute_minutes",
    "preferences",
    "weights",
}


def persist(state: OrchestratorState) -> dict:
    updates = {
        k: v for k, v in (state.persistable_field_updates or {}).items()
        if k in PERSISTABLE_KEYS
    }
    if state.target_area_id and "target_area_id" not in updates:
        updates["target_area_id"] = state.target_area_id
    if not updates or not state.session_id:
        return {}
    try:
        call_agent(
            "profile",
            task_type="profile.patch_slots",
            session_id=state.session_id,
            payload={"slots": updates},
            trace_id=state.trace_id,
        )
    except Exception as exc:
        logger.warning("persist failed (non-blocking): %s", exc)
    return {}
