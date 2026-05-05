from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field
from python_a2a import A2AServer, AgentCard as PyAgentCard, AgentSkill as PyAgentSkill
from python_a2a.server.http import create_flask_app

from app.config import settings
from nyc_agent_shared.a2a_protocol import (
    build_response_message,
    extract_request_content,
    legacy_a2a_response_to_content,
    request_content_to_legacy_a2a,
)
from nyc_agent_shared.llm_client import LlmClientError
from nyc_agent_shared.prompt_loader import list_prompts
from nyc_agent_shared.schemas import A2ARequest, A2AResponse, AgentCard, AgentSkill, ApiError

app = FastAPI(title="NYC Agent Weather Agent", version="0.1.0")


class WeatherToolPlan(BaseModel):
    status: str
    tool: str | None = None
    weather_result_type: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    missing_slots: list[str] = Field(default_factory=list)
    clarification: str = ""
    unsupported_reason: str = ""
    reason_summary: str = ""


weather_plan_parser = PydanticOutputParser(pydantic_object=WeatherToolPlan)

DATABASE_SCHEMA_STRING = """
-- 本项目真实库里 weather-agent 可直接依赖的核心表（用于 area 解析）：
CREATE TABLE IF NOT EXISTS app_area_dimension (
  area_id TEXT PRIMARY KEY,
  area_name TEXT NOT NULL,
  borough TEXT NOT NULL,
  area_type TEXT NULL,
  geom_geojson JSONB NULL,
  geom GEOMETRY(MULTIPOLYGON, 4326) NULL,
  updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- mcp-weather 会按 area_id/area_name 从 app_area_dimension.geom 解析坐标，
-- 再调用 NWS API 返回天气数据；MVP 不维护本地 weather_data 明细业务表。
"""

MCP_WEATHER_IO_SCHEMA = """
tool: get_current_weather
request.arguments:
{
  "area_id": string|null,
  "area_name": string|null,
  "latitude": number|null,
  "longitude": number|null
}
response.data(success):
{
  "area_name": string|null,
  "latitude": number,
  "longitude": number,
  "coord_source": string,
  "temperature": number|null,
  "temperature_unit": string|null,
  "short_forecast": string|null,
  "wind_speed": string|null,
  "wind_direction": string|null,
  "start_time": string|null,
  "end_time": string|null
}

tool: get_hourly_forecast
request.arguments:
{
  "area_id": string|null,
  "area_name": string|null,
  "latitude": number|null,
  "longitude": number|null,
  "hours": integer(1-24)
}
response.data(success):
{
  "area_name": string|null,
  "latitude": number,
  "longitude": number,
  "coord_source": string,
  "periods": array
}
"""

WEATHER_TOOL_PROMPT = ChatPromptTemplate.from_template(
    """
系统提示：你是天气查询工具规划器。你会接收对话历史和结构化槽位，决定调用哪个天气工具并给出参数。
- 只输出 JSON，不要额外文本。
- 无法确定必要参数时返回 clarification_required，不得编造。
- 可选工具: get_current_weather, get_hourly_forecast。
- transit/weather 属于实时工具链：不生成静态业务 SQL，不做离线表检索。
- 允许 mcp-weather 返回缓存数据作为降级结果。
- 必须严格遵守 mcp-weather 的输入字段白名单与输出字段语义。

Few-shot（最终输出必须是 JSON）：
- 对话: user: Astoria 现在天气怎么样
  输出:
  {{"status":"tool_ready","tool":"get_current_weather","weather_result_type":"current_weather","arguments":{{"area_id":"QN0101","area_name":"Astoria","latitude":null,"longitude":null,"hours":null}},"missing_slots":[],"clarification":"","unsupported_reason":"","reason_summary":"查询当前天气"}}
- 对话: user: LIC 未来6小时天气
  输出:
  {{"status":"tool_ready","tool":"get_hourly_forecast","weather_result_type":"hourly_forecast","arguments":{{"area_id":"QN0102","area_name":"Long Island City","latitude":null,"longitude":null,"hours":6}},"missing_slots":[],"clarification":"","unsupported_reason":"","reason_summary":"查询小时级预报"}}
- 对话: user: 我想看明天的天气
  输出:
  {{"status":"clarification_required","tool":"get_current_weather","weather_result_type":"current_weather","arguments":{{"area_id":null,"area_name":null,"latitude":null,"longitude":null,"hours":null}},"missing_slots":["target_area"],"clarification":"请告诉我你想查询纽约哪个区域的天气，例如 Astoria、Long Island City、Williamsburg。","unsupported_reason":"","reason_summary":"缺少目标区域"}}
- 对话: user: 帮我查天气
  输出:
  {{"status":"clarification_required","tool":"get_current_weather","weather_result_type":"current_weather","arguments":{{"area_id":null,"area_name":null,"latitude":null,"longitude":null,"hours":null}},"missing_slots":["target_area"],"clarification":"请先提供要查询的区域。","unsupported_reason":"","reason_summary":"缺少区域槽位"}}
- 对话: user: 你好
  输出:
  {{"status":"clarification_required","tool":"get_current_weather","weather_result_type":"current_weather","arguments":{{"area_id":null,"area_name":null,"latitude":null,"longitude":null,"hours":null}},"missing_slots":["target_area"],"clarification":"请提供天气查询信息，例如 'Astoria 今天天气'。","unsupported_reason":"","reason_summary":"非天气查询语句，需补充槽位"}}

输出 JSON 结构（仅工具计划）：
{{
  "status": "tool_ready" | "clarification_required" | "unsupported_data_request",
  "tool": "get_current_weather" | "get_hourly_forecast",
  "weather_result_type": "current_weather" | "hourly_forecast",
  "arguments": {{
    "area_id": string | null,
    "area_name": string | null,
    "latitude": number | null,
    "longitude": number | null,
    "hours": number | null
  }},
  "missing_slots": [string],
  "clarification": string,
  "unsupported_reason": string,
  "reason_summary": string
}}

输出必须满足以下格式约束：
{format_instructions}

可用的 area 字段语义（用于 area_id/area_name 理解）:
{database_schema}

mcp-weather JSON IO schema:
{mcp_weather_io_schema}

当前日期: {current_date} (America/New_York)
task_type: {task_type}
对话历史: {conversation}
slots_json: {slots_json}
domain_context_json: {domain_context_json}
"""
)


def a2a_error(
    req: A2ARequest,
    code: str,
    message: str,
    status: str = "error",
    retryable: bool = False,
    payload: dict[str, Any] | None = None,
) -> A2AResponse:
    return A2AResponse(
        trace_id=req.trace_id,
        session_id=req.session_id,
        source_agent="weather-agent",
        target_agent=req.source_agent,
        task_type=req.task_type,
        status=status,  # type: ignore[arg-type]
        payload=payload or {},
        error=ApiError(code=code, message=message, retryable=retryable),
    )


def call_tool(tool: str, session_id: str | None, arguments: dict[str, Any]) -> dict[str, Any]:
    with httpx.Client(timeout=settings.request_timeout_seconds) as client:
        response = client.post(
            f"{settings.mcp_weather_url.rstrip('/')}/tools/{tool}",
            json={"session_id": session_id, "arguments": arguments},
        )
        response.raise_for_status()
        return response.json()


def validate_plan(plan: dict[str, Any]) -> None:
    status = plan.get("status")
    if status not in {"tool_ready", "clarification_required", "unsupported_data_request"}:
        raise LlmClientError("Weather planner status is invalid.")
    if status != "tool_ready":
        return
    if plan.get("tool") not in {"get_current_weather", "get_hourly_forecast"}:
        raise LlmClientError("Weather planner tool is invalid.")
    if plan.get("weather_result_type") not in {"current_weather", "hourly_forecast"}:
        raise LlmClientError("Weather planner result type is invalid.")
    if not isinstance(plan.get("arguments"), dict):
        raise LlmClientError("Weather planner arguments must be an object.")


class WeatherQueryServer(A2AServer):
    def __init__(self) -> None:
        super().__init__(
            agent_card=PyAgentCard(
                name="weather-agent",
                description="NYC weather query agent driven by LangChain tool planning",
                url="http://weather-agent:8015",
                version="1.0.0",
                skills=[PyAgentSkill(name="execute weather query", description="execute weather query with MCP weather tools")],
                capabilities={"streaming": True, "memory": True},
                default_input_modes=["text"],
                default_output_modes=["text", "data"],
            )
        )
        self.llm = ChatOpenAI(
            model=settings.weather_agent_tool_model,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            timeout=settings.llm_request_timeout_seconds,
            temperature=0,
            model_kwargs={"response_format": {"type": "json_object"}},
        )
        self.chain = WEATHER_TOOL_PROMPT | self.llm

    def generate_tool_plan(
        self, *, task_type: str, conversation: str, slots: dict[str, Any], domain_context: dict[str, Any]
    ) -> dict[str, Any]:
        if not settings.openai_api_key:
            raise LlmClientError("OPENAI_API_KEY is required for weather tool planning.")
        current_date = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
        output = self.chain.invoke(
            {
                "format_instructions": weather_plan_parser.get_format_instructions(),
                "database_schema": DATABASE_SCHEMA_STRING,
                "mcp_weather_io_schema": MCP_WEATHER_IO_SCHEMA,
                "current_date": current_date,
                "task_type": task_type,
                "conversation": conversation,
                "slots_json": json.dumps(slots, ensure_ascii=False),
                "domain_context_json": json.dumps(domain_context, ensure_ascii=False),
            }
        )
        text = output.content if hasattr(output, "content") else str(output)
        plan_model = weather_plan_parser.parse(text)
        plan = plan_model.model_dump()
        validate_plan(plan)
        return plan

    def handle_message(self, message):
        content = extract_request_content(message)
        req = request_content_to_legacy_a2a(content)
        if not req.task_type.startswith("weather."):
            response = a2a_error(req, "UNSUPPORTED_TASK", f"unsupported weather task: {req.task_type}")
            response_content = legacy_a2a_response_to_content(response)
            return build_response_message(
                message,
                task_type=response_content["task_type"],
                status=response_content["status"],
                payload=response_content["payload"],
                source_agent="weather-agent",
                target_agent=response_content.get("target_agent"),
                trace_id=response_content.get("trace_id"),
                session_id=response_content.get("session_id"),
                error=response_content.get("error"),
                confidence=response_content.get("confidence"),
                data_quality=response_content.get("data_quality"),
            )

        try:
            plan = self.generate_tool_plan(
                task_type=req.task_type,
                conversation=str(req.payload.get("domain_user_query") or ""),
                slots=req.payload.get("slots") or {},
                domain_context=req.payload.get("domain_context") or {},
            )
        except Exception as exc:
            response = a2a_error(req, "WEATHER_PLANNER_FAILED", str(exc), status="dependency_failed", retryable=True)
            response_content = legacy_a2a_response_to_content(response)
            return build_response_message(
                message,
                task_type=response_content["task_type"],
                status=response_content["status"],
                payload=response_content["payload"],
                source_agent="weather-agent",
                target_agent=response_content.get("target_agent"),
                trace_id=response_content.get("trace_id"),
                session_id=response_content.get("session_id"),
                error=response_content.get("error"),
                confidence=response_content.get("confidence"),
                data_quality=response_content.get("data_quality"),
            )

        if plan["status"] in {"clarification_required", "unsupported_data_request"}:
            response = A2AResponse(
                trace_id=req.trace_id,
                session_id=req.session_id,
                source_agent="weather-agent",
                target_agent=req.source_agent,
                task_type=req.task_type,
                status=plan["status"],
                payload=plan,
                error=None,
            )
        else:
            tool = str(plan.get("tool") or "")
            args = plan.get("arguments") or {}
            try:
                result = call_tool(tool, req.session_id, args)
            except Exception as exc:
                response = a2a_error(
                    req,
                    "MCP_WEATHER_UNAVAILABLE",
                    str(exc),
                    status="dependency_failed",
                    retryable=True,
                    payload={"tool_plan": plan},
                )
            else:
                if result.get("status") in {"dependency_failed", "validation_error"}:
                    response = a2a_error(
                        req,
                        (result.get("error") or {}).get("code", "WEATHER_TOOL_ERROR"),
                        (result.get("error") or {}).get("message", "weather tool failed"),
                        status="dependency_failed",
                        retryable=True,
                        payload={"tool_result": result},
                    )
                else:
                    status = "success" if result.get("status") == "success" else "no_data"
                    weather_result = {
                        "status": status,
                        "domain": "weather",
                        "task_type": req.task_type,
                        "weather_result_type": plan.get("weather_result_type"),
                        "derived_metrics": result.get("data"),
                        "data_context": {
                            "source": "National Weather Service API",
                            "realtime_used": result.get("status") == "success",
                        },
                        "display_refs": {},
                    }
                    response = A2AResponse(
                        trace_id=req.trace_id,
                        session_id=req.session_id,
                        source_agent="weather-agent",
                        target_agent=req.source_agent,
                        task_type=req.task_type,
                        status=status,  # type: ignore[arg-type]
                        payload={"tool_plan": plan, "weather_result": weather_result, "tool_results": [result]},
                        error=None,
                    )

        response_content = legacy_a2a_response_to_content(response)
        return build_response_message(
            message,
            task_type=response_content["task_type"],
            status=response_content["status"],
            payload=response_content["payload"],
            source_agent="weather-agent",
            target_agent=response_content.get("target_agent"),
            trace_id=response_content.get("trace_id"),
            session_id=response_content.get("session_id"),
            error=response_content.get("error"),
            confidence=response_content.get("confidence"),
            data_quality=response_content.get("data_quality"),
        )


server = WeatherQueryServer()
app = create_flask_app(server)


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "weather-agent",
        "prompts_loaded": len(list_prompts()),
        "tool_planner": "llm_required",
    }


@app.get("/agent.json")
def http_agent_card() -> AgentCard:
    return AgentCard(
        name="Weather Query Assistant",
        description="基于LangChain提供天气查询服务的助手",
        url="http://weather-agent:8015",
        version="1.0.0",
        skills=[
            AgentSkill(
                id="weather_query",
                name="execute weather query",
                description="执行天气查询，返回天气工具结果，支持自然语言输入",
                task_types=["weather.current", "weather.hourly_forecast"],
            )
        ],
        capabilities={"streaming": True, "memory": True, "mcp": ["mcp-weather"]},
    )


@app.get("/ready")
def ready() -> dict[str, Any]:
    try:
        with httpx.Client(timeout=settings.request_timeout_seconds) as client:
            response = client.get(f"{settings.mcp_weather_url.rstrip('/')}/ready")
            response.raise_for_status()
        mcp = "ok"
    except Exception as exc:
        mcp = f"unavailable: {exc}"
    llm = "configured" if settings.openai_api_key else "missing_required"
    status = "ok" if mcp == "ok" and llm == "configured" else "degraded"
    return {"status": status, "dependencies": {"mcp-weather": mcp, "llm-tool-planner": llm}}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8015)
