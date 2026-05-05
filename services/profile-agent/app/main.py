from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from python_a2a import A2AServer, AgentCard as PyAgentCard, AgentSkill as PyAgentSkill
from python_a2a.server.http import create_flask_app

from app.config import settings
from nyc_agent_shared.a2a_protocol import (
    build_response_message,
    extract_request_content,
    legacy_a2a_response_to_content,
    request_content_to_legacy_a2a,
)
from nyc_agent_shared.llm_client import LlmClientError, parse_json_object
from nyc_agent_shared.prompt_loader import list_prompts
from nyc_agent_shared.schemas import A2ARequest, A2AResponse, AgentCard, AgentSkill, ApiError

app = FastAPI(title="NYC Agent Profile Agent", version="0.1.0")

DATABASE_SCHEMA_STRING = """
CREATE TABLE app_session_profile (
  session_id TEXT PRIMARY KEY,
  target_area_id TEXT NULL,
  budget_min NUMERIC(10,2) NULL,
  budget_max NUMERIC(10,2) NULL,
  target_destination TEXT NULL,
  max_commute_minutes INTEGER NULL,
  lease_term_months INTEGER NULL,
  move_in_date DATE NULL,
  weight_safety NUMERIC(5,2) NOT NULL,
  weight_commute NUMERIC(5,2) NOT NULL,
  weight_rent NUMERIC(5,2) NOT NULL,
  weight_convenience NUMERIC(5,2) NOT NULL,
  weight_entertainment NUMERIC(5,2) NOT NULL,
  weights_source TEXT NOT NULL,
  slots_json JSONB NOT NULL,
  missing_required JSONB NOT NULL,
  updated_at TIMESTAMP NOT NULL
);

CREATE TABLE app_session_recommendation (
  session_id TEXT NOT NULL,
  generated_at TIMESTAMP NOT NULL,
  rank_no INTEGER NOT NULL,
  area_id TEXT NOT NULL,
  total_score NUMERIC(6,2) NOT NULL,
  score_breakdown JSONB NOT NULL,
  reasons JSONB NOT NULL,
  risks JSONB NOT NULL
);
"""

PLAN_PROMPT = ChatPromptTemplate.from_template(
    """
系统提示：你是 Profile Tool 规划器。根据 task_type 和 payload 选择唯一 mcp-profile 工具及参数。
- 只输出 JSON，不要额外文本。
- 不得编造不存在字段。
- 必须在允许工具集合内选择：
  create_session / get_snapshot / patch_slots / update_weights / update_comparison_areas / save_conversation_summary / save_last_response_refs / delete_session

数据库 schema 语义（仅用于字段理解）:
{database_schema}

few-shot（工具规划）：
- task_type: profile.create_session
  payload: {{"session_id":"sess_1"}}
  output: {{"status":"tool_ready","tool":"create_session","arguments":{{"session_id":"sess_1"}},"missing_slots":[],"clarification":"","unsupported_reason":"","reason_summary":"创建会话"}}
- task_type: profile.patch_slots
  payload: {{"patch":{{"target_area_id":"QN0101","budget":{{"max":3000}}}}}}
  output: {{"status":"tool_ready","tool":"patch_slots","arguments":{{"patch":{{"target_area_id":"QN0101","budget":{{"max":3000}}}}}},"missing_slots":[],"clarification":"","unsupported_reason":"","reason_summary":"更新槽位"}}
- task_type: profile.save_conversation_summary
  payload: {{"summary":"用户关注 Astoria 的 1br 租金，预算 3000。"}}
  output: {{"status":"tool_ready","tool":"save_conversation_summary","arguments":{{"summary":"用户关注 Astoria 的 1br 租金，预算 3000。"}},"missing_slots":[],"clarification":"","unsupported_reason":"","reason_summary":"保存短摘要"}}

缺槽 few-shot：
- task_type: profile.create_session
  payload: {{}}
  output: {{"status":"clarification_required","tool":"create_session","arguments":{{}},"missing_slots":["session_id"],"clarification":"请提供 session_id。","unsupported_reason":"","reason_summary":"创建会话缺少 session_id"}}
- task_type: profile.patch_slots
  payload: {{}}
  output: {{"status":"clarification_required","tool":"patch_slots","arguments":{{}},"missing_slots":["patch"],"clarification":"请提供 patch 内容。","unsupported_reason":"","reason_summary":"缺少 patch"}}
- task_type: profile.update_weights
  payload: {{"weights":{{"safety":0.6}}}}
  output: {{"status":"tool_ready","tool":"update_weights","arguments":{{"weights":{{"safety":0.6}}}},"missing_slots":[],"clarification":"","unsupported_reason":"","reason_summary":"更新权重"}}

输出 JSON 结构：
{{
  "status": "tool_ready" | "clarification_required" | "unsupported_data_request",
  "tool": "create_session" | "get_snapshot" | "patch_slots" | "update_weights" | "update_comparison_areas" | "save_conversation_summary" | "save_last_response_refs" | "delete_session",
  "arguments": object,
  "missing_slots": [string],
  "clarification": string,
  "unsupported_reason": string,
  "reason_summary": string
}}

当前日期: {current_date} (America/New_York)
task_type: {task_type}
payload_json: {payload_json}
"""
)

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


def _deterministic_tool_plan(task_type: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    if task_type == "profile.get_snapshot":
        return {
            "status": "tool_ready",
            "tool": "get_snapshot",
            "arguments": {},
            "missing_slots": [],
            "clarification": "",
            "unsupported_reason": "",
            "reason_summary": "读取会话快照",
            "planner_mode": "deterministic",
        }
    if task_type == "profile.create_session":
        session_id = payload.get("session_id")
        if not session_id:
            return {
                "status": "clarification_required",
                "tool": "create_session",
                "arguments": {},
                "missing_slots": ["session_id"],
                "clarification": "请提供 session_id。",
                "unsupported_reason": "",
                "reason_summary": "创建会话缺少 session_id",
                "planner_mode": "deterministic",
            }
        return {
            "status": "tool_ready",
            "tool": "create_session",
            "arguments": {"session_id": session_id},
            "missing_slots": [],
            "clarification": "",
            "unsupported_reason": "",
            "reason_summary": "创建会话",
            "planner_mode": "deterministic",
        }
    if task_type == "profile.patch_slots":
        slots = payload.get("slots")
        if not isinstance(slots, dict):
            return {
                "status": "clarification_required",
                "tool": "patch_slots",
                "arguments": {},
                "missing_slots": ["slots"],
                "clarification": "请提供 slots。",
                "unsupported_reason": "",
                "reason_summary": "缺少 slots",
                "planner_mode": "deterministic",
            }
        return {
            "status": "tool_ready",
            "tool": "patch_slots",
            "arguments": {"slots": slots},
            "missing_slots": [],
            "clarification": "",
            "unsupported_reason": "",
            "reason_summary": "更新槽位",
            "planner_mode": "deterministic",
        }
    return None


def validate_plan(plan: dict[str, Any]) -> None:
    status = plan.get("status")
    if status not in {"tool_ready", "clarification_required", "unsupported_data_request"}:
        raise LlmClientError("Profile planner status is invalid.")
    tool = plan.get("tool")
    if tool and tool not in ALLOWED_TOOLS:
        raise LlmClientError("Profile planner tool is invalid.")
    if status == "tool_ready" and not isinstance(plan.get("arguments"), dict):
        raise LlmClientError("Profile planner arguments must be an object.")


def a2a_error(req: A2ARequest, code: str, message: str, retryable: bool = False) -> A2AResponse:
    return A2AResponse(
        trace_id=req.trace_id,
        session_id=req.session_id,
        source_agent="profile-agent",
        target_agent=req.source_agent,
        task_type=req.task_type,
        status="error",
        payload={},
        error=ApiError(code=code, message=message, retryable=retryable),
    )


def call_tool(tool: str, session_id: str | None, arguments: dict[str, Any]) -> dict[str, Any]:
    with httpx.Client(timeout=settings.request_timeout_seconds) as client:
        response = client.post(
            f"{settings.mcp_profile_url.rstrip('/')}/tools/{tool}",
            json={"session_id": session_id, "arguments": arguments},
        )
        response.raise_for_status()
        return response.json()


class ProfileQueryServer(A2AServer):
    def __init__(self) -> None:
        super().__init__(
            agent_card=PyAgentCard(
                name="profile-agent",
                description="NYC profile query agent driven by LangChain tool planning",
                url="http://profile-agent:8014",
                version="1.0.0",
                skills=[PyAgentSkill(name="execute profile tool", description="execute profile memory tools")],
                capabilities={"streaming": True, "memory": True},
                default_input_modes=["text"],
                default_output_modes=["text", "data"],
            )
        )
        self.llm = ChatOpenAI(
            model=settings.profile_agent_tool_model,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            timeout=settings.llm_request_timeout_seconds,
            temperature=0,
            model_kwargs={"response_format": {"type": "json_object"}},
        )
        self.chain = PLAN_PROMPT | self.llm

    def generate_tool_plan(self, *, task_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        deterministic_plan = _deterministic_tool_plan(task_type, payload)
        if deterministic_plan is not None:
            return deterministic_plan
        if not settings.openai_api_key:
            raise LlmClientError("OPENAI_API_KEY is required for profile tool planning.")
        current_date = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
        output = self.chain.invoke(
            {
                "database_schema": DATABASE_SCHEMA_STRING,
                "current_date": current_date,
                "task_type": task_type,
                "payload_json": json.dumps(payload, ensure_ascii=False),
            }
        ).content
        text = output if isinstance(output, str) else str(output)
        plan = parse_json_object(text)
        validate_plan(plan)
        plan["planner_mode"] = "llm"
        return plan

    def handle_message(self, message):
        content = extract_request_content(message)
        req = request_content_to_legacy_a2a(content)
        if not req.task_type.startswith("profile."):
            response = a2a_error(req, "UNSUPPORTED_TASK", f"unsupported profile task: {req.task_type}")
        else:
            payload = dict(req.payload or {})
            if req.task_type == "profile.create_session" and not payload.get("session_id"):
                payload["session_id"] = req.session_id or f"sess_{uuid4().hex[:16]}"
            try:
                plan = self.generate_tool_plan(task_type=req.task_type, payload=payload)
            except Exception as exc:
                response = a2a_error(req, "PROFILE_PLANNER_FAILED", str(exc), retryable=True)
            else:
                if plan["status"] in {"clarification_required", "unsupported_data_request"}:
                    response = A2AResponse(
                        trace_id=req.trace_id,
                        session_id=req.session_id,
                        source_agent="profile-agent",
                        target_agent=req.source_agent,
                        task_type=req.task_type,
                        status=plan["status"],
                        payload=plan,
                        error=None,
                    )
                else:
                    tool = str(plan.get("tool") or "")
                    try:
                        arguments = plan.get("arguments") or {}
                        if not isinstance(arguments, dict):
                            response = a2a_error(req, "PROFILE_PLANNER_INVALID", "planner arguments must be an object")
                        else:
                            result = call_tool(tool, req.session_id, arguments)
                            profile = result.get("data", {}).get("profile_snapshot")
                            status = "success" if result.get("status") == "success" else "error"
                            response = A2AResponse(
                                trace_id=req.trace_id,
                                session_id=(profile or {}).get("session_id", req.session_id),
                                source_agent="profile-agent",
                                target_agent=req.source_agent,
                                task_type=req.task_type,
                                status=status,
                                payload={"tool_plan": plan, "profile_snapshot": profile, "mcp_result": result},
                                error=None,
                            )
                    except httpx.HTTPStatusError as exc:
                        detail = exc.response.json().get("detail", {}) if exc.response.content else {}
                        error = detail.get("error") or {}
                        response = A2AResponse(
                            trace_id=req.trace_id,
                            session_id=req.session_id,
                            source_agent="profile-agent",
                            target_agent=req.source_agent,
                            task_type=req.task_type,
                            status="dependency_failed",
                            payload={"mcp_detail": detail},
                            error=ApiError(
                                code=error.get("code", "MCP_PROFILE_ERROR"),
                                message=error.get("message", str(exc)),
                                retryable=False,
                            ),
                        )
                    except Exception as exc:
                        response = a2a_error(req, "MCP_PROFILE_UNAVAILABLE", str(exc), retryable=True)

        response_content = legacy_a2a_response_to_content(response)
        return build_response_message(
            message,
            task_type=response_content["task_type"],
            status=response_content["status"],
            payload=response_content["payload"],
            source_agent="profile-agent",
            target_agent=response_content.get("target_agent"),
            trace_id=response_content.get("trace_id"),
            session_id=response_content.get("session_id"),
            error=response_content.get("error"),
            confidence=response_content.get("confidence"),
            data_quality=response_content.get("data_quality"),
        )


server = ProfileQueryServer()
app = create_flask_app(server)


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "service": "profile-agent", "prompts_loaded": len(list_prompts()), "tool_planner": "llm_required"}


@app.get("/agent.json")
def http_agent_card() -> AgentCard:
    return AgentCard(
        name="Profile Memory Assistant",
        description="基于LangChain提供会话画像与记忆管理的助手",
        url="http://profile-agent:8014",
        version="1.0.0",
        skills=[
            AgentSkill(
                id="profile_memory",
                name="execute profile tool",
                description="执行 profile 存储与读取工具，维护 session 记忆",
                task_types=[
                    "profile.create_session",
                    "profile.get_snapshot",
                    "profile.patch_slots",
                    "profile.update_weights",
                    "profile.update_comparison_areas",
                    "profile.save_conversation_summary",
                    "profile.save_last_response_refs",
                    "profile.delete_session",
                ],
            )
        ],
        capabilities={"streaming": True, "memory": True, "mcp": ["mcp-profile"]},
    )


@app.get("/ready")
def ready() -> dict[str, Any]:
    try:
        with httpx.Client(timeout=settings.request_timeout_seconds) as client:
            response = client.get(f"{settings.mcp_profile_url.rstrip('/')}/health")
            response.raise_for_status()
        mcp = "ok"
    except Exception as exc:
        mcp = f"unavailable: {exc}"
    llm = "configured" if settings.openai_api_key else "missing_required"
    status = "ok" if mcp == "ok" and llm == "configured" else "degraded"
    return {"status": status, "dependencies": {"mcp-profile": mcp, "llm-tool-planner": llm}}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8014)
