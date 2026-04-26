from __future__ import annotations

import json
import re
from typing import Any

import httpx


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
        body = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, indent=2)},
            ],
        }
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json=body,
                )
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            raise LlmClientError(f"LLM request failed: {exc}") from exc

        try:
            content = payload["choices"][0]["message"]["content"]
        except Exception as exc:
            raise LlmClientError("LLM response missing message content.") from exc
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
