"""Cut 8 — FastMCP layer for mcp-profile."""
from __future__ import annotations

from typing import Any

from app.main import (
    create_session as _legacy_create,
    delete_session as _legacy_delete,
    get_snapshot as _legacy_snapshot,
    patch_slots as _legacy_patch,
    save_conversation_summary as _legacy_save_summary,
    save_last_response_refs as _legacy_save_refs,
    update_comparison_areas as _legacy_update_areas,
    update_weights as _legacy_update_weights,
)
from nyc_agent_shared.mcp_protocol import build_mcp_server

mcp = build_mcp_server("mcp-profile")


def _wrap(arguments: dict[str, Any], session_id: str | None = None):
    from app.main import ToolRequest
    return ToolRequest(session_id=session_id, arguments=arguments)


@mcp.tool(name="create_session", description="Create a new anonymous session profile.")
def create_session() -> dict[str, Any]:
    return _legacy_create()


@mcp.tool(name="get_snapshot", description="Read the current profile snapshot for a session.")
def get_snapshot(session_id: str) -> dict[str, Any]:
    return _legacy_snapshot(_wrap({}, session_id=session_id))


@mcp.tool(name="patch_slots", description="Patch typed slots (target_area_id / budget / etc).")
def patch_slots(session_id: str, slots: dict[str, Any]) -> dict[str, Any]:
    return _legacy_patch(_wrap({"slots": slots}, session_id=session_id))


@mcp.tool(name="update_weights", description="Replace decision weights and renormalize.")
def update_weights(session_id: str, weights: dict[str, Any]) -> dict[str, Any]:
    return _legacy_update_weights(_wrap({"weights": weights}, session_id=session_id))


@mcp.tool(name="update_comparison_areas", description="Set the list of areas under comparison.")
def update_comparison_areas(session_id: str, areas: list[str]) -> dict[str, Any]:
    return _legacy_update_areas(_wrap({"areas": areas}, session_id=session_id))


@mcp.tool(name="save_conversation_summary", description="Persist the rolling conversation summary.")
def save_conversation_summary(session_id: str, summary: str) -> dict[str, Any]:
    return _legacy_save_summary(_wrap({"summary": summary}, session_id=session_id))


@mcp.tool(name="save_last_response_refs", description="Persist last_response_refs for traceability.")
def save_last_response_refs(session_id: str, last_response_refs: dict[str, Any]) -> dict[str, Any]:
    return _legacy_save_refs(_wrap({"last_response_refs": last_response_refs}, session_id=session_id))


@mcp.tool(name="delete_session", description="Delete the session and all stored profile state.")
def delete_session(session_id: str) -> dict[str, Any]:
    return _legacy_delete(_wrap({}, session_id=session_id))
