from __future__ import annotations

from typing import Any

from app.config import settings
from nyc_agent_shared.llm_client import JsonLlmClient, LlmClientError
from nyc_agent_shared.prompt_loader import load_prompt

WEATHER_SCHEMA_STRING = """
CREATE TABLE IF NOT EXISTS weather_data (
    id INT AUTO_INCREMENT PRIMARY KEY,
    city VARCHAR(50) NOT NULL,
    fx_date DATE NOT NULL,
    sunrise TIME,
    sunset TIME,
    moonrise TIME,
    moonset TIME,
    moon_phase VARCHAR(20),
    moon_phase_icon VARCHAR(10),
    temp_max INT,
    temp_min INT,
    icon_day VARCHAR(10),
    text_day VARCHAR(20),
    icon_night VARCHAR(10),
    text_night VARCHAR(20),
    wind360_day INT,
    wind_dir_day VARCHAR(20),
    wind_scale_day VARCHAR(10),
    wind_speed_day INT,
    wind360_night INT,
    wind_dir_night VARCHAR(20),
    wind_scale_night VARCHAR(10),
    wind_speed_night INT,
    precip DECIMAL(5,1),
    uv_index INT,
    humidity INT,
    pressure INT,
    vis INT,
    cloud INT,
    update_time DATETIME,
    UNIQUE KEY unique_city_date (city, fx_date)
);
"""

WEATHER_TOOL_SCHEMA = """
Return one JSON object:
{
  "status": "tool_ready" | "clarification_required" | "unsupported_data_request",
  "tool": "get_current_weather" | "get_hourly_forecast",
  "weather_result_type": "current_weather" | "hourly_forecast",
  "arguments": {
    "area_id": string | null,
    "area_name": string | null,
    "latitude": number | null,
    "longitude": number | null,
    "hours": number | null
  },
  "missing_slots": [string],
  "clarification": string,
  "unsupported_reason": string,
  "reason_summary": string
}
"""


def validate_plan(plan: dict[str, Any]) -> None:
    status = plan.get("status")
    if status not in {"tool_ready", "clarification_required", "unsupported_data_request"}:
        raise ValueError("Weather planner status is invalid.")
    if status != "tool_ready":
        return
    if plan.get("tool") not in {"get_current_weather", "get_hourly_forecast"}:
        raise ValueError("Weather tool is invalid.")
    if plan.get("weather_result_type") not in {"current_weather", "hourly_forecast"}:
        raise ValueError("Weather result_type is invalid.")
    if not isinstance(plan.get("arguments"), dict):
        raise ValueError("Weather arguments must be an object.")


def build_plan(task_type: str, query: str, slots: dict[str, Any], domain_context: dict[str, Any]) -> dict[str, Any]:
    if not settings.openai_api_key:
        raise LlmClientError("OPENAI_API_KEY is required for weather tool planning.")

    prompt = "\n\n".join(
        [
            load_prompt("weather/tool_plan_prompt.txt"),
            "你是天气 SQL/工具规划器。优先按 task_type 选择最匹配工具。",
            "仅输出 JSON，不输出解释。",
            "如果缺槽，不得编造，返回 clarification_required。",
            "用于上下文理解的数据表结构如下（仅作字段语义参考）：",
            WEATHER_SCHEMA_STRING,
            WEATHER_TOOL_SCHEMA,
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
        model=settings.weather_agent_tool_model,
        base_url=settings.openai_base_url,
        timeout_seconds=settings.llm_request_timeout_seconds,
    ).generate_json(system_prompt=prompt, user_payload=payload)
    validate_plan(plan)
    plan["planner_mode"] = "llm"
    return plan
