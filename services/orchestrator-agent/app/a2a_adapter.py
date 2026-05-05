"""Adapter for downstream A2A calls using python-a2a.

Agent-to-agent traffic uses python_a2a.A2AClient and python_a2a.Message.
Business context lives inside Message.content as a FunctionCallContent /
FunctionResponseContent payload, matching docs/NYC_Agent_A2A_Protocol.md.
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from python_a2a import A2AClient

from app.config import settings
from nyc_agent_shared.a2a_protocol import (
    build_request_message,
    extract_response_content,
)

logger = logging.getLogger(__name__)

try:
    from langsmith import traceable
except Exception:  # pragma: no cover — keep adapter usable when langsmith absent
    def traceable(*args, **kwargs):  # type: ignore[no-redef]
        def _decorator(fn):
            return fn
        return _decorator


def _new_trace_id() -> str:
    return f"trace_{uuid4().hex[:16]}"


@traceable(name="a2a.call_agent", run_type="tool")
def call_agent(
    target: str,
    *,
    task_type: str,
    session_id: str | None,
    payload: dict[str, Any],
    trace_id: str | None = None,
) -> dict[str, Any]:
    """Send a python-a2a Message to a downstream agent."""
    base_url = _resolve_base(target)
    trace_id = trace_id or _new_trace_id()
    message = build_request_message(
        task_type=task_type,
        payload=payload,
        trace_id=trace_id,
        session_id=session_id,
        source_agent="orchestrator-agent",
        target_agent=f"{target}-agent",
    )
    client = A2AClient(endpoint_url=base_url, timeout=int(settings.request_timeout_seconds))
    response = client.send_message(message)
    return extract_response_content(response)


def _resolve_base(target: str) -> str:
    mapping = {
        "neighborhood": settings.neighborhood_agent_url,
        "housing": settings.housing_agent_url,
        "transit": settings.transit_agent_url,
        "weather": settings.weather_agent_url,
        "profile": settings.profile_agent_url,
    }
    try:
        return mapping[target]
    except KeyError as exc:
        raise ValueError(f"unknown a2a target: {target}") from exc
