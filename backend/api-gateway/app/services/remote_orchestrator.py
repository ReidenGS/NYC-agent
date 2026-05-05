from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings


class RemoteOrchestratorClient:
    """Talks to the (single) orchestrator-agent.

    After cut 9 there's only one orchestrator — the LangGraph one —
    serving /sessions / /sessions/{id}/profile / /chat all from the same
    base URL. /chat gets a longer timeout because it triggers 2 LLM calls.
    """

    def __init__(self, base_url: str | None = None) -> None:
        self._explicit_base = base_url

    @property
    def base_url(self) -> str:
        return (self._explicit_base or settings.orchestrator_agent_url).rstrip("/")

    def _request(self, method: str, path: str, *, timeout: float | None = None, **kwargs) -> dict[str, Any]:
        with httpx.Client(timeout=timeout or settings.agent_request_timeout_seconds) as client:
            response = client.request(method, f"{self.base_url}{path}", **kwargs)
            response.raise_for_status()
            body = response.json()
        if not body.get("success", False):
            raise RuntimeError(body.get("error") or body)
        return body

    def create_session(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request("POST", "/sessions", json=payload or {})["data"]

    def get_profile(self, session_id: str) -> dict[str, Any]:
        return self._request("GET", f"/sessions/{session_id}/profile")["data"]

    def patch_profile(self, session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("PATCH", f"/sessions/{session_id}/profile", json=payload)["data"]

    def chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "POST", "/chat", json=payload,
            timeout=settings.chat_request_timeout_seconds,
        )["data"]

