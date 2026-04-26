from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings


class RemoteOrchestratorClient:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or settings.orchestrator_agent_url).rstrip("/")

    def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        with httpx.Client(timeout=settings.agent_request_timeout_seconds) as client:
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
        return self._request("POST", "/chat", json=payload)["data"]

