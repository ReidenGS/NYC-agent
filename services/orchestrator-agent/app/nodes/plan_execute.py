"""Node 4 — plan + execute (code, A2A calls).

Routes supported intents to downstream agents through python-a2a Message
calls handled by app.a2a_adapter.

Future cuts: add housing / transit / weather dispatch + parallel agent calls
for comparison intent.
"""
from __future__ import annotations

import logging

from app.a2a_adapter import call_agent
from app.state import AgentResult, OrchestratorState

logger = logging.getLogger(__name__)

NEIGHBORHOOD_INTENTS = {
    "neighborhood.crime_query",
    "neighborhood.convenience_query",
    "neighborhood.entertainment_query",
    "area.metrics_query",
}

WEATHER_INTENTS = {
    "weather.current",
    "weather.hourly_forecast",
}

HOUSING_INTENTS = {
    "housing.rent_query",
    "housing.listing_search",
}

TRANSIT_INTENTS = {
    "transit.realtime_commute",
    "transit.next_departure",
}


def _area_slots(state: OrchestratorState) -> dict:
    """Common (area_id, area_name) slot block used by every domain agent."""
    return {
        "area_id": {
            "value": state.target_area_id,
            "source": "session_memory",
            "confidence": 0.9,
        },
        "area_name": {
            "value": state.target_area_name,
            "source": "session_memory",
            "confidence": 0.9,
        },
    }


def _build_neighborhood_payload(state: OrchestratorState) -> dict:
    return {
        "domain_user_query": state.current_user_message,
        "slots": _area_slots(state),
        "domain_context": {"window_days": 30, "point_limit": 20, "map_layer_requests": []},
    }


def _build_weather_payload(state: OrchestratorState) -> dict:
    # weather-agent reads area_id from slots and uses domain_context.hours
    # to bound the forecast window. 6 hours is the orchestrator default.
    return {
        "domain_user_query": state.current_user_message,
        "slots": _area_slots(state),
        "domain_context": {"hours": 6},
    }


def _extract_budget_monthly(state: OrchestratorState) -> float | None:
    """Pull monthly rent budget from any of the shapes the LLM may return.

    Tolerates: constraints.budget_monthly (number), constraints.budget.max
    (object), persistable_field_updates.budget.max. First non-empty wins.
    """
    c = state.constraints or {}
    if c.get("budget_monthly") is not None:
        try:
            return float(c["budget_monthly"])
        except (TypeError, ValueError):
            pass
    raw_budget = c.get("budget")
    if isinstance(raw_budget, dict) and raw_budget.get("max") is not None:
        try:
            return float(raw_budget["max"])
        except (TypeError, ValueError):
            pass
    if isinstance(raw_budget, (int, float)):
        return float(raw_budget)
    persisted = (state.persistable_field_updates or {}).get("budget") or {}
    if isinstance(persisted, dict) and persisted.get("max") is not None:
        try:
            return float(persisted["max"])
        except (TypeError, ValueError):
            pass
    return None


_BEDROOM_NORMALIZE = {
    # housing-agent expects studio / 1br / 2br / 3br / 4br tokens.
    "studio": "studio", "开间": "studio", "studios": "studio",
    "1": "1br", "1b": "1br", "1br": "1br", "1bd": "1br",
    "1b1b": "1br", "1bed1bath": "1br",
    "1-bedroom": "1br", "1 bedroom": "1br", "one-bedroom": "1br",
    "一居": "1br", "一室": "1br", "1居": "1br",
    "2": "2br", "2b": "2br", "2br": "2br", "2bd": "2br",
    "2b2b": "2br", "2bed2bath": "2br",
    "2-bedroom": "2br", "2 bedroom": "2br", "two-bedroom": "2br",
    "两居": "2br", "两室": "2br", "2居": "2br",
    "3": "3br", "3b": "3br", "3br": "3br", "3b3b": "3br", "三居": "3br",
}


def _extract_bedroom_type(state: OrchestratorState) -> str | None:
    """Pull bedroom and normalize it into housing-agent's enum.

    The LLM understand node may store this under various keys/values
    (`bedroom`, `bedroom_type`, '一居', '1b', '1 bedroom', ...). Map
    everything down to studio/1br/2br/3br/4br before sending downstream.
    """
    c = state.constraints or {}
    raw = c.get("bedroom_type") or c.get("bedroom")
    if not raw:
        # Last resort: scan the user's current message for an obvious token
        # that the LLM might have missed (e.g. "1 居" with stray space).
        message = (state.current_user_message or "").lower()
        for token, normalized in _BEDROOM_NORMALIZE.items():
            if token in message:
                return normalized
        return None
    key = str(raw).strip().lower()
    key = key.replace(" ", "").replace("-", "")
    return _BEDROOM_NORMALIZE.get(key, key)


_MODE_NORMALIZE = {
    "subway": "subway", "地铁": "subway", "train": "subway", "metro": "subway",
    "bus": "bus", "公交": "bus",
    "either": "either", "都可以": "either",
}


def _extract_mode(state: OrchestratorState) -> str | None:
    c = state.constraints or {}
    raw = c.get("mode") or c.get("transit_mode") or c.get("transport")
    if raw:
        return _MODE_NORMALIZE.get(str(raw).strip().lower(), str(raw).strip().lower())
    msg = (state.current_user_message or "").lower()
    for token, normalized in _MODE_NORMALIZE.items():
        if token in msg:
            return normalized
    return None


def _build_transit_payload(state: OrchestratorState) -> dict:
    """transit-agent reads origin/destination/mode for realtime_commute,
    or mode/route_id/stop_name/direction for next_departure. Slots come
    from constraints (LLM-extracted) with light Python fallbacks."""
    c = state.constraints or {}
    slots: dict = {}
    mode = _extract_mode(state)
    if mode:
        slots["mode"] = {"value": mode, "source": "user_explicit", "confidence": 0.85}
    if state.intent == "transit.realtime_commute":
        for k in ("origin", "destination"):
            resolved = c.get(f"{k}_resolved")
            if isinstance(resolved, dict) and resolved.get("entity_id"):
                # RAG-resolved → ship structured object (kind + entity_id + lat/lon)
                # so transit-agent / mcp-transit can pick stop_id vs area_id directly.
                slots[k] = {
                    "value": resolved,
                    "source": "rag_resolved",
                    "confidence": float(resolved.get("score") or 0.85),
                }
            elif c.get(k):
                slots[k] = {"value": c[k], "source": "user_explicit", "confidence": 0.85}
        if c.get("route_id"):
            slots["route_id"] = {"value": c["route_id"], "source": "user_explicit", "confidence": 0.8}
    else:  # transit.next_departure
        stop_resolved = c.get("stop_name_resolved")
        if isinstance(stop_resolved, dict) and stop_resolved.get("entity_id"):
            slots["stop_name"] = {
                "value": stop_resolved,
                "source": "rag_resolved",
                "confidence": float(stop_resolved.get("score") or 0.85),
            }
        elif c.get("stop_name"):
            slots["stop_name"] = {"value": c["stop_name"], "source": "user_explicit", "confidence": 0.8}
        for k in ("route_id", "direction"):
            v = c.get(k)
            if v:
                slots[k] = {"value": v, "source": "user_explicit", "confidence": 0.8}
    return {
        "domain_user_query": state.current_user_message,
        "slots": slots,
        "domain_context": {"departure_count": 2, "cache_ttl_seconds": 60},
    }


def _build_housing_payload(state: OrchestratorState) -> dict:
    """housing-agent reads area_id (required), bedroom_type (required for
    budget_fit / listing_candidates), and budget_monthly from slots."""
    slots = _area_slots(state)
    bedroom = _extract_bedroom_type(state)
    if bedroom:
        slots["bedroom_type"] = {
            "value": bedroom, "source": "user_explicit", "confidence": 0.9,
        }
    budget = _extract_budget_monthly(state)
    if budget is not None:
        slots["budget_monthly"] = {
            "value": budget, "source": "user_explicit", "confidence": 0.9,
        }
    return {
        "domain_user_query": state.current_user_message,
        "slots": slots,
        "domain_context": {"currency": "USD", "listing_limit": 5},
    }


def _dispatch_single(state: OrchestratorState, target: str, build_payload, task_type: str | None = None) -> AgentResult:
    """Call one downstream agent and wrap the response into AgentResult."""
    outbound_task_type = task_type or state.intent or "unknown"
    try:
        response = call_agent(
            target,
            task_type=outbound_task_type,
            session_id=state.session_id,
            payload=build_payload(state),
            trace_id=state.trace_id,
        )
        return AgentResult(
            agent=f"{target}-agent",
            task_type=outbound_task_type,
            status=response.get("status", "error"),
            payload=response.get("payload") or {},
            error=response.get("error"),
        )
    except Exception as exc:
        logger.exception("%s-agent A2A call failed", target)
        return AgentResult(
            agent=f"{target}-agent",
            task_type=outbound_task_type,
            status="dependency_failed",
            payload={},
            error={"code": "A2A_TRANSPORT_ERROR", "message": str(exc), "retryable": True},
        )


def _comparison_dimension_to_intent(dim: str) -> tuple[str, str]:
    """Map a comparison dimension to (target_agent, task_type)."""
    dim = dim.strip().lower()
    if dim in {"safety", "安全", "crime", "犯罪"}:
        return "neighborhood", "neighborhood.crime_query"
    if dim in {"convenience", "便利", "amenity"}:
        return "neighborhood", "neighborhood.convenience_query"
    if dim in {"entertainment", "娱乐"}:
        return "neighborhood", "neighborhood.entertainment_query"
    if dim in {"rent", "租金", "housing"}:
        return "housing", "housing.rent_query"
    if dim in {"commute", "通勤", "transit"}:
        return "neighborhood", "area.metrics_query"  # transit needs origin; fall back to area metrics for now
    if dim in {"weather", "天气"}:
        return "weather", "weather.current"
    return "neighborhood", "area.metrics_query"


def _build_comparison_payload(state: OrchestratorState, area_id: str, area_name: str | None, task_type: str) -> dict:
    return {
        "domain_user_query": state.current_user_message,
        "slots": {
            "area_id": {"value": area_id, "source": "user_explicit", "confidence": 0.9},
            "area_name": {"value": area_name or area_id, "source": "user_explicit", "confidence": 0.9},
        },
        "domain_context": (
            {"window_days": 30, "point_limit": 20, "map_layer_requests": []}
            if task_type.startswith("neighborhood.") or task_type == "area.metrics_query"
            else {"hours": 6} if task_type.startswith("weather.")
            else {"currency": "USD", "listing_limit": 5}
        ),
    }


def _dispatch_comparison(state: OrchestratorState) -> list[AgentResult]:
    """Comparison fans out N parallel A2A calls — one per (area, dimension)
    pair. First cut runs them sequentially (httpx in a thread pool would let
    us parallelize; deferring to a future cut)."""
    dim = (state.constraints or {}).get("comparison_dimension")
    areas = state.detected_areas or []
    if not dim or len(areas) < 2:
        return [
            AgentResult(
                agent="orchestrator-v2",
                task_type="comparison",
                status="clarification_required",
                payload={
                    "missing_slots": [
                        s for s in (
                            "comparison_dimension" if not dim else None,
                            "comparison_areas" if len(areas) < 2 else None,
                        ) if s
                    ],
                    "clarification": "需要至少 2 个区域和一个比较维度（安全/租金/通勤/便利/娱乐）。",
                },
            )
        ]
    target, task_type = _comparison_dimension_to_intent(str(dim))
    results: list[AgentResult] = []
    builder = (lambda a_id, a_name: lambda s: _build_comparison_payload(s, a_id, a_name, task_type))
    for area in areas:
        if not area.area_id:
            continue
        # Override target_area in this single call without mutating state.
        bound = builder(area.area_id, area.area_name)
        try:
            response = call_agent(
                target,
                task_type=task_type,
                session_id=state.session_id,
                payload=bound(state),
                trace_id=state.trace_id,
            )
            results.append(AgentResult(
                agent=f"{target}-agent",
                task_type=task_type,
                status=response.get("status", "error"),
                payload={"area_id": area.area_id, "area_name": area.area_name, **(response.get("payload") or {})},
                error=response.get("error"),
            ))
        except Exception as exc:
            logger.exception("comparison dispatch failed for %s", area.area_id)
            results.append(AgentResult(
                agent=f"{target}-agent",
                task_type=task_type,
                status="dependency_failed",
                payload={"area_id": area.area_id},
                error={"code": "A2A_TRANSPORT_ERROR", "message": str(exc), "retryable": True},
            ))
    return results


def _dispatch_by_intent(state: OrchestratorState, intent: str) -> AgentResult | list[AgentResult]:
    if intent in NEIGHBORHOOD_INTENTS:
        return _dispatch_single(state, "neighborhood", _build_neighborhood_payload, task_type=intent)
    if intent in WEATHER_INTENTS:
        return _dispatch_single(state, "weather", _build_weather_payload, task_type=intent)
    if intent in HOUSING_INTENTS:
        return _dispatch_single(state, "housing", _build_housing_payload, task_type=intent)
    if intent in TRANSIT_INTENTS:
        return _dispatch_single(state, "transit", _build_transit_payload, task_type=intent)
    if intent == "comparison":
        return _dispatch_comparison(state)
    if intent == "out_of_scope":
        return AgentResult(
            agent="orchestrator-v2",
            task_type="out_of_scope",
            status="success",
            payload={
                "reason": "User request does not require a domain agent.",
                "respond_with_llm": True,
            },
        )
    return AgentResult(
        agent="orchestrator-v2",
        task_type=intent,
        status="unsupported_data_request",
        payload={"reason": f"intent {intent} not yet implemented in orchestrator-v2"},
    )


def plan_execute(state: OrchestratorState) -> dict:
    intent = state.intent or "unknown"
    intent_sequence = (state.constraints or {}).get("intent_sequence")
    if isinstance(intent_sequence, list) and len(intent_sequence) > 1:
        results: list[AgentResult] = []
        for item in intent_sequence:
            dispatched = _dispatch_by_intent(state, str(item))
            if isinstance(dispatched, list):
                results.extend(dispatched)
            else:
                results.append(dispatched)
        return {"agent_results": results}

    if intent in NEIGHBORHOOD_INTENTS:
        return {"agent_results": [_dispatch_single(state, "neighborhood", _build_neighborhood_payload)]}
    if intent in WEATHER_INTENTS:
        return {"agent_results": [_dispatch_single(state, "weather", _build_weather_payload)]}
    if intent in HOUSING_INTENTS:
        return {"agent_results": [_dispatch_single(state, "housing", _build_housing_payload)]}
    if intent in TRANSIT_INTENTS:
        return {"agent_results": [_dispatch_single(state, "transit", _build_transit_payload)]}
    if intent == "comparison":
        return {"agent_results": _dispatch_comparison(state)}
    if intent in {"out_of_scope", "chitchat"}:
        # No domain agent call; respond node will let the LLM answer inside
        # the identity/scope boundary.
        return {
            "agent_results": [
                AgentResult(
                    agent="orchestrator-v2",
                    task_type="out_of_scope",
                    status="success",
                    payload={
                        "reason": "User request does not require a domain agent.",
                        "respond_with_llm": True,
                    },
                )
            ]
        }

    # Truly unknown — let respond produce a generic fallback.
    return {
        "agent_results": [
            AgentResult(
                agent="orchestrator-v2",
                task_type=intent,
                status="unsupported_data_request",
                payload={"reason": f"intent {intent} not yet implemented in orchestrator-v2"},
            )
        ]
    }
