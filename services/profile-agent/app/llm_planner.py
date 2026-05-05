from __future__ import annotations

from typing import Any

from app.config import settings
from nyc_agent_shared.llm_client import JsonLlmClient, LlmClientError
from nyc_agent_shared.prompt_loader import load_prompt

ALLOWED_TOOLS = {
    "create_session",
    "get_snapshot",
    "patch_slots",
    "update_weights",
    "update_comparison_areas",
    "save_conversation_summary",
    "save_last_response_refs",
    "delete_session",
}

PROFILE_TOOL_SCHEMA = """
Return one JSON object:
{
  "status": "tool_ready" | "clarification_required" | "unsupported_data_request",
  "tool": "create_session" | "get_snapshot" | "patch_slots" | "update_weights" | "update_comparison_areas" | "save_conversation_summary" | "save_last_response_refs" | "delete_session",
  "arguments": object,
  "missing_slots": [string],
  "clarification": string,
  "unsupported_reason": string,
  "reason_summary": string
}
"""


def validate_plan(plan: dict[str, Any]) -> None:
    status = plan.get("status")
    if status not in {"tool_ready", "clarification_required", "unsupported_data_request"}:
        raise ValueError("Profile planner status is invalid.")
    if status != "tool_ready":
        return
    if plan.get("tool") not in ALLOWED_TOOLS:
        raise ValueError("Profile planner tool is invalid.")
    if not isinstance(plan.get("arguments"), dict):
        raise ValueError("Profile planner arguments must be an object.")


def build_plan(task_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not settings.openai_api_key:
        raise LlmClientError("OPENAI_API_KEY is required for profile tool planning.")

    prompt = "\n\n".join(
        [
            load_prompt("profile/tool_plan_prompt.txt"),
            "你是 profile 工具规划器。根据 task_type 与 payload 选择唯一 MCP profile tool。",
            "仅输出 JSON，不输出解释。",
            PROFILE_TOOL_SCHEMA,
        ]
    )
    plan = JsonLlmClient(
        api_key=settings.openai_api_key,
        model=settings.profile_agent_tool_model,
        base_url=settings.openai_base_url,
        timeout_seconds=settings.llm_request_timeout_seconds,
    ).generate_json(
        system_prompt=prompt,
        user_payload={"task_type": task_type, "payload": payload},
    )
    validate_plan(plan)
    plan["planner_mode"] = "llm"
    return plan
