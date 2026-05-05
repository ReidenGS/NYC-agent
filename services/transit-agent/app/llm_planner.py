from __future__ import annotations

from typing import Any

from app.config import settings
from nyc_agent_shared.llm_client import JsonLlmClient, LlmClientError
from nyc_agent_shared.prompt_loader import load_prompt

TRANSIT_TOOL_SCHEMA = """
Return one JSON object:
{
  "status": "tool_ready" | "clarification_required" | "unsupported_data_request",
  "transit_result_type": "next_departure" | "realtime_commute",
  "execution_steps": [
    {
      "tool": "resolve_station_or_stop" | "get_next_departures" | "get_realtime_commute",
      "arguments": object
    }
  ],
  "missing_slots": [string],
  "clarification": string,
  "unsupported_reason": string,
  "reason_summary": string
}
"""


def validate_plan(plan: dict[str, Any]) -> None:
    status = plan.get("status")
    if status not in {"tool_ready", "clarification_required", "unsupported_data_request"}:
        raise ValueError("Transit planner status is invalid.")
    if status != "tool_ready":
        return
    if plan.get("transit_result_type") not in {"next_departure", "realtime_commute"}:
        raise ValueError("Transit result_type is invalid.")
    steps = plan.get("execution_steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("Transit execution_steps must be a non-empty list.")
    allowed = {"resolve_station_or_stop", "get_next_departures", "get_realtime_commute"}
    for step in steps:
        if not isinstance(step, dict):
            raise ValueError("Transit step must be an object.")
        if step.get("tool") not in allowed:
            raise ValueError("Transit step tool is invalid.")
        if not isinstance(step.get("arguments"), dict):
            raise ValueError("Transit step arguments must be an object.")


def build_plan(task_type: str, query: str, slots: dict[str, Any], domain_context: dict[str, Any]) -> dict[str, Any]:
    if not settings.openai_api_key:
        raise LlmClientError("OPENAI_API_KEY is required for transit tool planning.")

    prompt = "\n\n".join(
        [
            load_prompt("transit/tool_plan_prompt.txt"),
            "你是 transit 工具规划器。根据 task_type 和上下文生成执行步骤。",
            "仅输出 JSON，不输出解释。",
            "缺参数必须返回 clarification_required，不得编造。",
            TRANSIT_TOOL_SCHEMA,
        ]
    )
    payload = {
        "task_type": task_type,
        "domain_user_query": query,
        "slots": slots,
        "domain_context": domain_context,
    }
    plan = JsonLlmClient(
        api_key=settings.openai_api_key,
        model=settings.transit_agent_tool_model,
        base_url=settings.openai_base_url,
        timeout_seconds=settings.llm_request_timeout_seconds,
    ).generate_json(system_prompt=prompt, user_payload=payload)
    validate_plan(plan)
    plan["planner_mode"] = "llm"
    return plan
