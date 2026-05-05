"""Pydantic schema + PydanticOutputParser for the understand LLM node.

Per docs/NYC_Agent_Backend_Tech_Framework.md §2.1 path 1: provider-agnostic
parser-style structured output. The schema is rendered into the prompt via
`parser.get_format_instructions()`, and LLM text output is parsed back into
the typed model. No provider-native function calling is required.
"""
from __future__ import annotations

from typing import Any, Literal

from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field

# --- Node 2 (understand) -----------------------------------------------------
SUPPORTED_INTENTS = Literal[
    "neighborhood.crime_query",
    "neighborhood.convenience_query",
    "neighborhood.entertainment_query",
    "area.metrics_query",
    "housing.rent_query",
    "housing.listing_search",
    "transit.realtime_commute",
    "transit.next_departure",
    "weather.current",
    "weather.hourly_forecast",
    "comparison",
    "out_of_scope",
    "chitchat",
    "unknown",
]


class DetectedAreaOut(BaseModel):
    area_id: str | None = Field(None, description="NTA code like QN0101 if known; null if only the name was mentioned")
    area_name: str | None = Field(None, description="Human-facing name like 'Astoria'")
    source: Literal["user_explicit", "session_memory", "llm_inferred"] = "user_explicit"


class IntentResult(BaseModel):
    """Output of Node 2 (understand)."""

    intent: SUPPORTED_INTENTS = Field(
        ...,
        description=(
            "Primary intent for this turn. For compound queries, this must be "
            "the first item of constraints.intent_sequence."
        ),
    )
    detected_areas: list[DetectedAreaOut] = Field(
        default_factory=list,
        description="Areas the user mentioned in this message. Empty if the user did not name any area.",
    )
    constraints: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Extracted slots and routing metadata. For compound queries, include "
            "intent_sequence as a list of supported intents in the user's natural order. "
            "Also include slot values such as budget, bedroom_type, origin, destination, "
            "mode, route_id, stop_name, target_time, comparison_dimension, etc."
        ),
    )
    persistable_field_updates: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Subset of constraints + areas that should be PERSISTED to mcp-profile. "
            "Keys must match app_session_profile columns: target_area_id, budget, "
            "target_destination, max_commute_minutes, preferences, weights. "
            "Leave empty for normal Q&A turns; only fill when the user explicitly "
            "states a stable preference (e.g. '我预算 2500' → {'budget': {'max': 2500}})."
        ),
    )
    confidence: float = Field(0.5, ge=0.0, le=1.0)


intent_parser = PydanticOutputParser(pydantic_object=IntentResult)
