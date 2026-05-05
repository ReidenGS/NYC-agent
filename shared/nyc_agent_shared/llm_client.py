from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI


class LlmClientError(RuntimeError):
    pass


class JsonLlmClient:
    def __init__(self, *, api_key: str, model: str, base_url: str = "https://api.openai.com/v1", timeout_seconds: float = 20.0) -> None:
        self.api_key = api_key.strip()
        self.model = model.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        if not self.api_key:
            raise LlmClientError("OPENAI_API_KEY is not configured.")
        if not self.model:
            raise LlmClientError("LLM model is not configured.")

    def generate_json(self, *, system_prompt: str, user_payload: dict[str, Any]) -> dict[str, Any]:
        llm = ChatOpenAI(
            model=self.model,
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout_seconds,
            temperature=0,
            model_kwargs={"response_format": {"type": "json_object"}},
        )
        try:
            response = llm.invoke(
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=json.dumps(user_payload, ensure_ascii=False, indent=2)),
                ]
            )
        except Exception as exc:
            raise LlmClientError(f"LLM request failed: {exc}") from exc

        try:
            content = response.content
        except Exception as exc:
            raise LlmClientError("LLM response missing message content.") from exc
        if not isinstance(content, str):
            content = str(content)
        return parse_json_object(content)


def parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, re.DOTALL | re.IGNORECASE)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise LlmClientError("LLM output is not valid JSON.") from exc
    if not isinstance(value, dict):
        raise LlmClientError("LLM output must be a JSON object.")
    return value
