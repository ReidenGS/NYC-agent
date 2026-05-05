"""Node 3 — gate (rule-based).

Validate required slots for the current intent. Missing slot → mark for
follow-up; gate routes to respond_ask in graph.py.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.state import OrchestratorState, PendingFollowUp

# What each intent demands. First cut covers neighborhood + a placeholder for
# unknown; expand as more intents are wired in plan_execute.
REQUIRED_SLOTS: dict[str, list[str]] = {
    "neighborhood.crime_query":         ["target_area"],
    "neighborhood.convenience_query":   ["target_area"],
    "neighborhood.entertainment_query": ["target_area"],
    "area.metrics_query":               ["target_area"],
    "weather.current":                  ["target_area"],
    "weather.hourly_forecast":          ["target_area"],
    "housing.rent_query":               ["target_area"],
    "housing.listing_search":           ["target_area"],
    # transit gates: realtime_commute needs origin+destination (not target_area);
    # next_departure needs route+stop. transit-agent itself returns
    # clarification_required for these — orchestrator only validates target_area
    # is set if the user is asking a transit question that lacks origin info.
    "transit.realtime_commute":         [],
    "transit.next_departure":           [],
    "comparison":                       ["comparison_dimension"],  # also needs >=2 areas, checked separately
}


def gate(state: OrchestratorState) -> dict:
    intent = state.intent or "unknown"
    required = REQUIRED_SLOTS.get(intent, [])
    missing: list[str] = []
    constraints = state.constraints or {}

    if intent in {"housing.rent_query", "housing.listing_search"}:
        bedroom = constraints.get("bedroom_type")
        if not bedroom and constraints.get("bedroom_unrecognized"):
            missing.append("bedroom_type")

    for slot in required:
        if slot == "target_area" and not state.target_area_id:
            missing.append("target_area")
        elif slot == "comparison_dimension" and "comparison_dimension" not in constraints:
            missing.append("comparison_dimension")

    # Comparison also needs ≥2 areas. If gate sees only 0 or 1 area mentioned,
    # ask the user to name the second.
    if intent == "comparison" and len(state.detected_areas or []) < 2:
        missing.append("comparison_areas")

    if missing:
        prompt_text = None
        if "bedroom_type" in missing:
            prompt_text = "我没明白你说的户型。可以用例如：studio、1br、2br、3br。"
        elif "target_area" in missing:
            area_resolution = constraints.get("area_resolution") or {}
            if area_resolution.get("method") == "vector_rag" and not area_resolution.get("resolved"):
                candidates = area_resolution.get("candidates") or []
                if candidates:
                    readable = []
                    for item in candidates[:3]:
                        name = item.get("area_name")
                        borough = item.get("borough")
                        if name:
                            readable.append(f"{name} ({borough})" if borough else str(name))
                    if readable:
                        prompt_text = "我没能精确识别你说的区域。你是指：" + "、".join(readable) + "？"

        # Mark pending so the next /chat turn's backfill node can match.
        pending = PendingFollowUp(
            asked_slot=missing[0],
            asked_intent=intent,
            asked_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            prompt_text=prompt_text,
            missing_slots=missing,
            original_user_query=state.current_user_message,
            partial_constraints=state.constraints or {},
        )
        return {"final_missing_slots": missing, "pending_follow_up": pending}
    return {"final_missing_slots": []}
